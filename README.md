A small tool, provides the following feature:
***
## 1. Add selected bones to several selected Meshes:
- Select the bones (Pose Mode, Edit Mode, or Object Mode).
- Select the meshes that should get empty vertex groups, and one armature. Either the mesh or the armature can be active. If more than one armature is selected, make the one you want active.
- Run **Selected Bones to Vertex Group > Add To Vertex Group**.
  - Object Mode: right-click, or Object > Parent
  - Pose Mode and Armature Edit Mode: header menu or right-click
  - Weight Paint: Weights menu
- The status bar reports how many groups were added. Bones that already have a group are left as they are.
- If a mesh has no Armature modifier for that armature, one is added. An Armature modifier with no armature set is reused instead of adding a second one.
- Only deform bones are included by default. Turn off **Only Deform Bones** in the redo panel to include control bones.
***
## 2. Delete selected bones from several selected Meshes:
- Use the same selection as above.
- Run **Delete From Vertex Group**.
***
Note: You can select several meshes but one armature.

Install `Selected_Bones_to_Vertex_Group_v1.0.2.zip`, or install the `Selected_Bones_To_Vertex_Group` folder. Version 1.0.2 fixes adding or deleting groups for more than one bone on a mesh that already has groups from this add-on.
