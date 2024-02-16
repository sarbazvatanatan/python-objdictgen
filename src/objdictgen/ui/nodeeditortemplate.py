#
# Copyright (C) 2022-2024  Svein Seldal, Laerdal Medical AS
# Copyright (C): Edouard TISSERANT, Francis DUPIN and Laurent BESSARD
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301
# USA

import wx

from objdictgen.maps import OD
from objdictgen.ui import commondialogs as cdia
from objdictgen.ui.exception import display_error_dialog, display_exception_dialog


class NodeEditorTemplate:

    EDITMENU_ID = None

    def __init__(self, manager, frame, mode_solo):
        self.Manager = manager
        self.Frame = frame
        self.ModeSolo = mode_solo

        self.BusId = None
        self.Closing = False

    def GetBusId(self):
        return self.BusId

    def IsClosing(self):
        return self.Closing

    def OnAddSDOServerMenu(self, event):  # pylint: disable=unused-argument
        self.Manager.AddSDOServerToCurrent()
        self.RefreshBufferState()
        self.RefreshCurrentIndexList()

    def OnAddSDOClientMenu(self, event):  # pylint: disable=unused-argument
        self.Manager.AddSDOClientToCurrent()
        self.RefreshBufferState()
        self.RefreshCurrentIndexList()

    def OnAddPDOTransmitMenu(self, event):  # pylint: disable=unused-argument
        self.Manager.AddPDOTransmitToCurrent()
        self.RefreshBufferState()
        self.RefreshCurrentIndexList()

    def OnAddPDOReceiveMenu(self, event):  # pylint: disable=unused-argument
        self.Manager.AddPDOReceiveToCurrent()
        self.RefreshBufferState()
        self.RefreshCurrentIndexList()

    def OnAddMapVariableMenu(self, event):  # pylint: disable=unused-argument
        self.AddMapVariable()

    def OnAddUserTypeMenu(self, event):  # pylint: disable=unused-argument
        self.AddUserType()

    def OnRefreshMenu(self, event):  # pylint: disable=unused-argument
        self.RefreshCurrentIndexList()

    def RefreshCurrentIndexList(self):
        pass

    def RefreshStatusBar(self):
        pass

    def SetStatusBarText(self, selection, manager):
        if selection:
            index, subindex = selection
            if manager.IsCurrentEntry(index):
                self.Frame.HelpBar.SetStatusText(f"Index: 0x{index:04X}", 0)
                self.Frame.HelpBar.SetStatusText(f"Subindex: 0x{subindex:02X}", 1)
                entryinfos = manager.GetEntryInfos(index)
                name = entryinfos["name"]
                category = "Optional"
                if entryinfos["need"]:
                    category = "Mandatory"
                struct = "VAR"
                number = ""
                if entryinfos["struct"] & OD.IdenticalIndexes:
                    number = f" possibly defined {entryinfos['nbmax']} times"
                if entryinfos["struct"] & OD.IdenticalSubindexes:
                    struct = "ARRAY"
                elif entryinfos["struct"] & OD.MultipleSubindexes:
                    struct = "RECORD"
                text = f"{name}: {category} entry of struct {struct}{number}."
                self.Frame.HelpBar.SetStatusText(text, 2)
            else:
                for i in range(3):
                    self.Frame.HelpBar.SetStatusText("", i)
        else:
            for i in range(3):
                self.Frame.HelpBar.SetStatusText("", i)

    def RefreshProfileMenu(self):
        if self.EDITMENU_ID is not None:
            profile = self.Manager.GetCurrentProfileName()
            edititem = self.Frame.EditMenu.FindItemById(self.EDITMENU_ID)
            if edititem:
                length = self.Frame.AddMenu.GetMenuItemCount()
                for _ in range(length - 6):
                    additem = self.Frame.AddMenu.FindItemByPosition(6)
                    self.Frame.AddMenu.Delete(additem.GetId())
                if profile not in ("None", "DS-301"):
                    edititem.SetItemLabel(f"{profile} Profile")
                    edititem.Enable(True)
                    self.Frame.AddMenu.AppendSeparator()
                    for text, _ in self.Manager.GetCurrentSpecificMenu():
                        new_id = wx.NewId()
                        self.Frame.AddMenu.Append(helpString='', id=new_id, kind=wx.ITEM_NORMAL, item=text)
                        self.Frame.Bind(wx.EVT_MENU, self.GetProfileCallBack(text), id=new_id)
                else:
                    edititem.SetItemLabel("Other Profile")
                    edititem.Enable(False)

# ------------------------------------------------------------------------------
#                            Buffer Functions
# ------------------------------------------------------------------------------

    def RefreshBufferState(self):
        pass

    def OnUndoMenu(self, event):  # pylint: disable=unused-argument
        self.Manager.LoadCurrentPrevious()
        self.RefreshCurrentIndexList()
        self.RefreshBufferState()

    def OnRedoMenu(self, event):  # pylint: disable=unused-argument
        self.Manager.LoadCurrentNext()
        self.RefreshCurrentIndexList()
        self.RefreshBufferState()

# ------------------------------------------------------------------------------
#                          Editing Profiles functions
# ------------------------------------------------------------------------------

    def OnCommunicationMenu(self, event):  # pylint: disable=unused-argument
        dictionary, current = self.Manager.GetCurrentCommunicationLists()
        self.EditProfile("Edit DS-301 Profile", dictionary, current)

    def OnOtherCommunicationMenu(self, event):  # pylint: disable=unused-argument
        dictionary, current = self.Manager.GetCurrentDS302Lists()
        self.EditProfile("Edit DS-302 Profile", dictionary, current)

    def OnEditProfileMenu(self, event):  # pylint: disable=unused-argument
        title = f"Edit {self.Manager.GetCurrentProfileName()} Profile"
        dictionary, current = self.Manager.GetCurrentProfileLists()
        self.EditProfile(title, dictionary, current)

    def EditProfile(self, title, dictionary, current):
        dialog = cdia.CommunicationDialog(self.Frame)
        dialog.SetTitle(title)
        dialog.SetIndexDictionary(dictionary)
        dialog.SetCurrentList(current)
        dialog.RefreshLists()
        if dialog.ShowModal() == wx.ID_OK:
            new_profile = dialog.GetCurrentList()
            addinglist = []
            removinglist = []
            for index in new_profile:
                if index not in current:
                    addinglist.append(index)
            for index in current:
                if index not in new_profile:
                    removinglist.append(index)
            self.Manager.ManageEntriesOfCurrent(addinglist, removinglist)
            self.Manager.BufferCurrentNode()
            self.RefreshBufferState()

        dialog.Destroy()

    def GetProfileCallBack(self, text):
        def ProfileCallBack(event):  # pylint: disable=unused-argument
            self.Manager.AddSpecificEntryToCurrent(text)
            self.RefreshBufferState()
            self.RefreshCurrentIndexList()
        return ProfileCallBack

# ------------------------------------------------------------------------------
#                         Edit Node informations function
# ------------------------------------------------------------------------------

    def OnNodeInfosMenu(self, event):  # pylint: disable=unused-argument
        dialog = cdia.NodeInfosDialog(self.Frame)
        name, id_, type_, description = self.Manager.GetCurrentNodeInfos()
        defaultstringsize = self.Manager.GetCurrentNodeDefaultStringSize()
        dialog.SetValues(name, id_, type_, description, defaultstringsize)
        if dialog.ShowModal() == wx.ID_OK:
            name, id_, type_, description, defaultstringsize = dialog.GetValues()
            self.Manager.SetCurrentNodeInfos(name, id_, type_, description)
            self.Manager.SetCurrentNodeDefaultStringSize(defaultstringsize)
            self.RefreshBufferState()
            self.RefreshCurrentIndexList()
            self.RefreshProfileMenu()

# ------------------------------------------------------------------------------
#                           Add User Types and Variables
# ------------------------------------------------------------------------------

    def AddMapVariable(self):
        index = self.Manager.GetCurrentNextMapIndex()
        if index:
            dialog = cdia.MapVariableDialog(self.Frame)
            dialog.SetIndex(index)
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    self.Manager.AddMapVariableToCurrent(*dialog.GetValues())
                    self.RefreshBufferState()
                    self.RefreshCurrentIndexList()
                except Exception as exc:  # pylint: disable=broad-except
                    display_exception_dialog(self.Frame)
            dialog.Destroy()
        else:
            display_error_dialog(self.Frame, "No map variable index left!")

    def AddUserType(self):
        dialog = cdia.UserTypeDialog(self)
        dialog.SetTypeList(self.Manager.GetCustomisableTypes())
        if dialog.ShowModal() == wx.ID_OK:
            try:
                self.Manager.AddUserTypeToCurrent(*dialog.GetValues())
                self.RefreshBufferState()
                self.RefreshCurrentIndexList()
            except Exception as exc:  # pylint: disable=broad-except
                display_exception_dialog(self.Frame)
        dialog.Destroy()
