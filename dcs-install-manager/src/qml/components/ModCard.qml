import QtQuick
import DcsInstallManager

// One catalog entry row: name/status, module/category/description, and
// Install-or-Uninstall / Edit / Delete actions.
Rectangle {
    id: card

    property string entryId: ""
    property string entryName: ""
    property string description: ""
    property string module: ""
    property string category: ""
    property bool isInstalled: false
    property bool needsReinstall: false

    signal editClicked()
    signal installClicked()
    signal uninstallClicked()
    signal deleteClicked()

    color: Theme.colorSurface
    radius: Theme.radiusMedium
    border.width: 1
    border.color: Theme.colorBorder
    implicitHeight: Math.max(contentColumn.implicitHeight, buttonsRow.implicitHeight)
                    + Theme.spacingMedium * 2

    Column {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: buttonsRow.left
        anchors.top: parent.top
        anchors.margins: Theme.spacingMedium
        anchors.rightMargin: Theme.spacingMedium
        spacing: Theme.spacingSmall

        Row {
            spacing: Theme.spacingSmall
            Text {
                text: card.entryName
                color: Theme.colorText
                font.pixelSize: 15
                font.bold: true
            }
            StatusBadge {
                installed: card.isInstalled
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        Text {
            text: card.module + " · " + card.category
                  + (card.needsReinstall ? " · reinstall after DCS update" : "")
            color: Theme.colorTextMuted
            font.pixelSize: 12
        }

        Text {
            visible: card.description.length > 0
            text: card.description
            color: Theme.colorText
            font.pixelSize: 13
            wrapMode: Text.WordWrap
            width: contentColumn.width
        }
    }

    Row {
        id: buttonsRow
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Theme.spacingMedium
        spacing: Theme.spacingSmall

        FlatButton {
            text: card.isInstalled ? "Uninstall" : "Install"
            accentColor: card.isInstalled ? Theme.colorDanger : Theme.colorAccentBlue
            onClicked: card.isInstalled ? card.uninstallClicked() : card.installClicked()
        }
        FlatButton {
            text: "Edit"
            accentColor: Theme.colorBorder
            textColor: Theme.colorText
            onClicked: card.editClicked()
        }
        FlatButton {
            text: "Delete"
            accentColor: Theme.colorDanger
            onClicked: card.deleteClicked()
        }
    }
}
