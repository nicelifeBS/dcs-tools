import QtQuick
import QtQuick.Controls.Basic as Basic
import DcsInstallManager

// Flat, rounded combo box. Only background/contentItem/indicator are overridden; the
// popup/delegate stay the Basic style's own (already flat and minimal) defaults.
Basic.ComboBox {
    id: control

    implicitHeight: 34
    font.pixelSize: 13

    background: Rectangle {
        radius: Theme.radiusSmall
        color: control.enabled ? Theme.colorSurface : Theme.colorBackground
        border.width: 1
        border.color: (control.activeFocus || control.popup.visible) ? Theme.colorAccentBlue
                                                                       : Theme.colorBorder
    }

    contentItem: Text {
        text: control.displayText
        color: Theme.colorText
        font: control.font
        leftPadding: 10
        rightPadding: 24
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Text {
        text: "▾"
        color: Theme.colorTextMuted
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
    }
}
