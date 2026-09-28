import QtQuick
import QtQuick.Controls.Basic as Basic
import DcsInstallManager

// The main catalog screen: one ModCard per catalog entry, wired to real
// add/edit/delete + install/uninstall backend calls. catalogModel and modInstaller
// are exposed as QQmlContext properties from main.cpp.
Rectangle {
    id: root

    signal editRequested(string entryId)

    color: Theme.colorBackground

    property string pendingAction: "" // "delete" | "uninstall"
    property string pendingEntryId: ""

    ListView {
        id: listView
        anchors.fill: parent
        anchors.margins: Theme.spacingLarge
        clip: true
        spacing: Theme.spacingMedium
        model: catalogModel

        Basic.ScrollBar.vertical: Basic.ScrollBar {}

        delegate: ModCard {
            width: listView.width
            entryId: model.id
            entryName: model.name
            description: model.description
            module: model.module
            category: model.category
            isInstalled: model.isInstalled
            needsReinstall: model.needsReinstallAfterUpdate

            onEditClicked: root.editRequested(entryId)

            onInstallClicked: {
                const result = modInstaller.installEntry(entryId)
                if (!result.success) {
                    errorDialog.titleText = "Install Failed"
                    errorDialog.message = result.message
                    errorDialog.open()
                }
            }

            onUninstallClicked: {
                root.pendingAction = "uninstall"
                root.pendingEntryId = entryId
                confirmDialog.titleText = "Uninstall Entry"
                confirmDialog.message = "Uninstall \"" + entryName
                                         + "\"? Any backed-up original file will be restored."
                confirmDialog.confirmColor = Theme.colorDanger
                confirmDialog.open()
            }

            onDeleteClicked: {
                root.pendingAction = "delete"
                root.pendingEntryId = entryId
                confirmDialog.titleText = "Delete Entry"
                confirmDialog.message = "Delete catalog entry \"" + entryName
                                         + "\"? This does not uninstall its files."
                confirmDialog.confirmColor = Theme.colorDanger
                confirmDialog.open()
            }
        }
    }

    Text {
        anchors.centerIn: parent
        visible: listView.count === 0
        text: "No catalog entries yet.\nClick \"Add Entry\" above to create one."
        horizontalAlignment: Text.AlignHCenter
        color: Theme.colorTextMuted
        font.pixelSize: 14
    }

    ConfirmDialog {
        id: confirmDialog
        parent: root
        onAccepted: {
            if (root.pendingAction === "delete") {
                catalogModel.removeEntry(root.pendingEntryId)
            } else if (root.pendingAction === "uninstall") {
                const result = modInstaller.uninstallEntry(root.pendingEntryId)
                if (!result.success) {
                    errorDialog.titleText = "Uninstall Failed"
                    errorDialog.message = result.message
                    errorDialog.open()
                }
            }
        }
    }

    ConfirmDialog {
        id: errorDialog
        parent: root
        showCancel: false
        confirmColor: Theme.colorAccentBlue
    }
}
