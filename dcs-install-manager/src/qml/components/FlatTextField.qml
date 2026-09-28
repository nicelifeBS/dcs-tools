import QtQuick
import QtQuick.Controls.Basic as Basic
import DcsInstallManager

// Flat, rounded, 1px-bordered text field (border color shifts on focus rather than
// any elevation/glow effect).
Basic.TextField {
    id: control

    implicitHeight: 34
    color: Theme.colorText
    placeholderTextColor: Theme.colorTextMuted
    selectionColor: Theme.colorAccentBlue
    selectedTextColor: "white"
    font.pixelSize: 13
    leftPadding: 10
    rightPadding: 10
    topPadding: 0
    bottomPadding: 0
    verticalAlignment: Text.AlignVCenter

    background: Rectangle {
        radius: Theme.radiusSmall
        color: control.enabled ? Theme.colorSurface : Theme.colorBackground
        border.width: 1
        border.color: control.activeFocus ? Theme.colorAccentBlue : Theme.colorBorder
    }
}
