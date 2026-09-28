import QtQuick
import QtQuick.Controls.Basic as Basic
import DcsInstallManager

// Generic flat confirmation dialog, used for delete/uninstall confirmations and for
// surfacing ModInstaller failure messages (e.g. "Close DCS before
// installing/uninstalling mods") with showCancel: false.
Basic.Dialog {
    id: dialog

    property alias titleText: dialog.title
    property alias message: messageLabel.text
    property bool showCancel: true
    property color confirmColor: Theme.colorDanger

    modal: true
    width: 380
    x: (parent ? (parent.width - width) / 2 : 0)
    y: (parent ? (parent.height - height) / 2 : 0)

    background: Rectangle {
        radius: Theme.radiusMedium
        color: Theme.colorSurface
        border.width: 1
        border.color: Theme.colorBorder
    }

    header: Text {
        text: dialog.title
        color: Theme.colorText
        font.pixelSize: 15
        font.bold: true
        padding: Theme.spacingMedium
        bottomPadding: 0
    }

    contentItem: Text {
        id: messageLabel
        color: Theme.colorText
        font.pixelSize: 13
        wrapMode: Text.WordWrap
        padding: Theme.spacingMedium
    }

    footer: Item {
        implicitHeight: buttonRow.implicitHeight + Theme.spacingMedium * 2
        Row {
            id: buttonRow
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.rightMargin: Theme.spacingMedium
            spacing: Theme.spacingSmall

            FlatButton {
                text: "Cancel"
                visible: dialog.showCancel
                accentColor: Theme.colorBorder
                textColor: Theme.colorText
                onClicked: dialog.reject()
            }
            FlatButton {
                text: "OK"
                accentColor: dialog.confirmColor
                onClicked: dialog.accept()
            }
        }
    }
}
