# -*- coding: utf-8 -*-
import maya.cmds as cmds
import maya.mel as mel

def create_shelf():
    shelf_name = "mLender"
    
    # Check if shelf already exists
    if cmds.shelfLayout(shelf_name, exists=True):
        # Empty it so we can rebuild
        children = cmds.shelfLayout(shelf_name, query=True, childArray=True) or []
        for child in children:
            cmds.deleteUI(child)
    else:
        # Create new shelf
        mel.eval('addNewShelfTab "{0}"'.format(shelf_name))
    
    # Set parent to our shelf so buttons go inside
    cmds.setParent(shelf_name)
    
    cmds.shelfButton(
        annotation="Open mLender Export Interface",
        image1="pythonFamily.png", 
        command="import mlender_exporter as ml; ml.show_ui()",
        label="mLender",
        imageOverlayLabel="mLender",
        overlayLabelColor=(1, 1, 1),
        overlayLabelBackColor=(0.1, 0.1, 0.1, 0.5)
    )
