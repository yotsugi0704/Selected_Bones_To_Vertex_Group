# SPDX-License-Identifier: GPL-3.0-or-later
"""Add or delete vertex groups for the bones that are actually selected."""

import bpy
from bpy.types import Menu, Operator

_POLL_MESSAGES = {
    "no_mesh": "Select at least one mesh",
    "no_armature": "Select an armature, or a mesh deformed by one",
    "ambiguous_armature": "Multiple armatures selected; make the one you want active",
}

_MENU_HOOKS = (
    "VIEW3D_MT_object_parent",
    "VIEW3D_MT_object_context_menu",
    "VIEW3D_MT_pose",
    "VIEW3D_MT_pose_context_menu",
    "VIEW3D_MT_edit_armature",
    "VIEW3D_MT_armature_context_menu",
    "VIEW3D_MT_paint_weight",
    "MESH_MT_vertex_group_context_menu",
)


def _set_poll_message(cls, message):
    setter = getattr(cls, "poll_message_set", None)
    if setter is not None:
        setter(message)


def _poll_targets(cls, context):
    _armature, _meshes, reason = gather_targets(context)
    if reason is not None:
        _set_poll_message(cls, _POLL_MESSAGES.get(reason, "Select an armature and a mesh"))
        return False
    _set_poll_message(cls, "")
    return True


def _flag(operator, name, default):
    """Operator properties are RNA after registration; fall back if they are not."""
    value = getattr(operator, name, default)
    return default if not isinstance(value, bool) else value


def _armature_from_mesh(mesh):
    """Armature already driving this mesh, if any."""
    for mod in getattr(mesh, "modifiers", ()):
        if getattr(mod, "type", None) == "ARMATURE" and getattr(mod, "object", None) is not None:
            if getattr(mod.object, "type", None) == "ARMATURE":
                return mod.object
    parent = getattr(mesh, "parent", None)
    if parent is not None and getattr(parent, "type", None) == "ARMATURE":
        return parent
    return None


def gather_targets(context):
    """Return (armature, meshes, reason).

    reason is None when both targets are usable. Armature does not have to be
    the active object: weight paint and "mesh active, armature selected" are
    valid. The old poll required the armature to be active, so the operator
    was greyed out for those selections and appeared to do nothing.
    """
    selected = [
        obj
        for obj in (getattr(context, "selected_objects", None) or [])
        if obj is not None
    ]
    active = getattr(context, "active_object", None)

    meshes = []
    for obj in selected:
        if getattr(obj, "type", None) == "MESH" and obj not in meshes:
            meshes.append(obj)
    if active is not None and getattr(active, "type", None) == "MESH" and active not in meshes:
        meshes.append(active)

    selected_arms = [obj for obj in selected if getattr(obj, "type", None) == "ARMATURE"]

    if active is not None and getattr(active, "type", None) == "ARMATURE":
        armature = active
        reason = None
    elif len(selected_arms) == 1:
        armature = selected_arms[0]
        reason = None
    elif len(selected_arms) > 1:
        armature = None
        reason = "ambiguous_armature"
    else:
        pose_object = getattr(context, "pose_object", None)
        if pose_object is not None and getattr(pose_object, "type", None) == "ARMATURE":
            armature = pose_object
            reason = None
        else:
            inferred = []
            for mesh in meshes:
                arm = _armature_from_mesh(mesh)
                if arm is not None and arm not in inferred:
                    inferred.append(arm)
            if len(inferred) == 1:
                armature = inferred[0]
                reason = None
            elif len(inferred) > 1:
                armature = None
                reason = "ambiguous_armature"
            else:
                armature = None
                reason = "no_armature"

    if armature is None:
        return None, meshes, reason or "no_armature"
    if not meshes:
        return armature, [], "no_mesh"
    return armature, meshes, None


def selected_bone_records(armature, context):
    """Selected bones as plain (name, use_deform) tuples.

    Names are copied before any mesh is edited. Two things used to make a
    second batch of bones do nothing:

    * ``mode_set(mode='EDIT')`` can drop every selected bone except the
      active one. If that bone already had a group, the operator finished
      without creating anything.
    * Holding ``EditBone`` references across ``vertex_groups.new()`` or
      ``modifiers.new()`` invalidates them. The next bone then raises
      ``ReferenceError``, and Blender cancels the operator.
    """
    if getattr(armature, "mode", None) == "EDIT":
        return [
            (bone.name, bool(bone.use_deform))
            for bone in armature.data.edit_bones
            if bone.select
        ]

    # Pose selection is authoritative while this armature is being posed
    # (pose mode and weight paint). data.bones can still reflect an older
    # selection after the user has already changed which bones are selected.
    if getattr(context, "pose_object", None) == armature:
        pose_bones = getattr(context, "selected_pose_bones", None) or []
        if pose_bones:
            return [(pb.name, bool(pb.bone.use_deform)) for pb in pose_bones]

    return [
        (bone.name, bool(bone.use_deform))
        for bone in armature.data.bones
        if bone.select
    ]


def filter_bone_names(records, only_deform):
    names = []
    seen = set()
    skipped = 0
    for name, use_deform in records:
        if not name or name in seen:
            continue
        seen.add(name)
        if only_deform and not use_deform:
            skipped += 1
            continue
        names.append(name)
    return names, skipped


def ensure_armature_modifier(mesh, armature):
    """Return True when a new modifier was created."""
    modifiers = mesh.modifiers
    for mod in modifiers:
        if getattr(mod, "type", None) == "ARMATURE" and getattr(mod, "object", None) == armature:
            return False
    for mod in modifiers:
        if getattr(mod, "type", None) == "ARMATURE" and getattr(mod, "object", None) is None:
            mod.object = armature
            return False
    mod = modifiers.new(name=armature.name, type="ARMATURE")
    mod.object = armature
    return True


def add_groups_for_bones(mesh, bone_names):
    added = []
    existed = []
    for name in bone_names:
        if mesh.vertex_groups.get(name) is None:
            mesh.vertex_groups.new(name=name)
            added.append(name)
        else:
            existed.append(name)
    if added:
        group = mesh.vertex_groups.get(added[-1])
        index = getattr(group, "index", None)
        if index is not None:
            mesh.vertex_groups.active_index = index
    return added, existed


def remove_groups_for_bones(mesh, bone_names):
    removed = []
    missing = []
    for name in bone_names:
        group = mesh.vertex_groups.get(name)
        if group is None:
            missing.append(name)
            continue
        mesh.vertex_groups.remove(group)
        removed.append(name)
    return removed, missing


def _targets_ready(operator, context):
    armature, meshes, reason = gather_targets(context)
    if reason is not None or armature is None or not meshes:
        operator.report({"WARNING"}, _POLL_MESSAGES.get(reason, "Select an armature and a mesh"))
        return None, None
    return armature, meshes


class Add_Selected_VGroup(Operator):
    bl_idname = "wm.add_vgroup_to_select"
    bl_label = "Add To Vertex Group"
    bl_description = (
        "Create an empty vertex group for each selected bone on the selected meshes, "
        "and add an Armature modifier if the mesh does not have one"
    )
    bl_options = {"REGISTER", "UNDO"}

    only_deform: bpy.props.BoolProperty(
        name="Only Deform Bones",
        description="Skip bones that do not have Deform enabled. Turn this off in the redo panel to include control bones",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return _poll_targets(cls, context)

    def execute(self, context):
        armature, meshes = _targets_ready(self, context)
        if armature is None:
            return {"CANCELLED"}

        # Snapshot before creating modifiers or groups. Those edits invalidate
        # EditBone/PoseBone RNA, which used to abort the operator on bone 2.
        bone_names, skipped = filter_bone_names(
            list(selected_bone_records(armature, context)),
            _flag(self, "only_deform", True),
        )
        if not bone_names:
            if skipped:
                self.report(
                    {"WARNING"},
                    f"No deform bones selected ({skipped} selected bone(s) have Deform off)",
                )
            else:
                self.report({"WARNING"}, "No bones selected")
            return {"CANCELLED"}

        added = 0
        existed = 0
        mods = 0
        errors = []
        for mesh in meshes:
            try:
                if ensure_armature_modifier(mesh, armature):
                    mods += 1
                new_names, old_names = add_groups_for_bones(mesh, bone_names)
            except RuntimeError as exc:
                errors.append(f"{getattr(mesh, 'name', 'mesh')}: {exc}")
                continue
            added += len(new_names)
            existed += len(old_names)

        if added == 0 and errors:
            self.report({"ERROR"}, "; ".join(errors))
            return {"CANCELLED"}

        if added == 0 and existed and not errors:
            message = f"Selected bones already have vertex groups ({existed})"
            level = "WARNING"
        elif added == 0:
            message = "No vertex groups were added"
            level = "WARNING"
        else:
            if len(meshes) == 1:
                target = f"on '{meshes[0].name}'"
            else:
                target = f"on {len(meshes)} meshes"
            message = f"Added {added} vertex group(s) {target}"
            level = "INFO"

        extras = []
        if added and existed:
            extras.append(f"{existed} already existed")
        if mods:
            extras.append(f"added {mods} Armature modifier(s)")
        if skipped:
            extras.append(f"skipped {skipped} non-deform bone(s)")
        if errors:
            extras.append("; ".join(errors))
            level = "WARNING"
        if extras:
            message = message + "; " + "; ".join(extras)
        self.report({level}, message)
        return {"FINISHED"}


class Delete_Selected_VGroup(Operator):
    bl_idname = "wm.delete_vgroup_to_select"
    bl_label = "Delete From Vertex Group"
    bl_description = "Delete vertex groups named after the selected bones from the selected meshes"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_targets(cls, context)

    def execute(self, context):
        armature, meshes = _targets_ready(self, context)
        if armature is None:
            return {"CANCELLED"}

        bone_names, _skipped = filter_bone_names(
            list(selected_bone_records(armature, context)),
            only_deform=False,
        )
        if not bone_names:
            self.report({"WARNING"}, "No bones selected")
            return {"CANCELLED"}

        removed = 0
        missing = 0
        errors = []
        for mesh in meshes:
            try:
                gone, absent = remove_groups_for_bones(mesh, bone_names)
            except RuntimeError as exc:
                errors.append(f"{getattr(mesh, 'name', 'mesh')}: {exc}")
                continue
            removed += len(gone)
            missing += len(absent)

        if removed == 0 and errors:
            self.report({"ERROR"}, "; ".join(errors))
            return {"CANCELLED"}
        if removed == 0:
            self.report({"WARNING"}, "Selected bones have no vertex groups to delete")
            return {"FINISHED"}

        if len(meshes) == 1:
            target = f"from '{meshes[0].name}'"
        else:
            target = f"from {len(meshes)} meshes"
        message = f"Deleted {removed} vertex group(s) {target}"
        if missing:
            message += f"; {missing} already missing"
        if errors:
            message += "; " + "; ".join(errors)
        self.report({"INFO"} if not errors else {"WARNING"}, message)
        return {"FINISHED"}


class OBJECT_MT_draw_menu(Menu):
    bl_idname = "OBJECT_MT_add_del_menu"
    bl_label = "Selected Bones to Vertex Group"

    def draw(self, context):
        layout = self.layout
        layout.operator(Add_Selected_VGroup.bl_idname)
        layout.operator(Delete_Selected_VGroup.bl_idname)


def draw_menu(self, context):
    self.layout.separator()
    self.layout.menu(OBJECT_MT_draw_menu.bl_idname)


def register():
    bpy.utils.register_class(OBJECT_MT_draw_menu)
    bpy.utils.register_class(Add_Selected_VGroup)
    bpy.utils.register_class(Delete_Selected_VGroup)
    for name in _MENU_HOOKS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.append(draw_menu)


def unregister():
    for name in reversed(_MENU_HOOKS):
        menu = getattr(bpy.types, name, None)
        if menu is None:
            continue
        try:
            menu.remove(draw_menu)
        except (ValueError, RuntimeError):
            pass
    bpy.utils.unregister_class(Delete_Selected_VGroup)
    bpy.utils.unregister_class(Add_Selected_VGroup)
    bpy.utils.unregister_class(OBJECT_MT_draw_menu)


if __name__ == "__main__":
    try:
        unregister()
    except Exception:
        pass
    register()
