import QtQuick
import QtQuick.Controls.Basic as Basic
import DcsInstallManager

// Flat, rounded, single-color button. Built on top of QtQuick.Controls.Basic (Qt's
// own minimal "unstyled" style, which already has no gradients/bevels/shadows) rather
// than a formally registered custom QQC2 style - see the milestone-4 report for why.
Basic.Button {
    id: control

    property color accentColor: Theme.colorAccentBlue
    property color textColor: "white"

    implicitWidth: Math.max(72, contentItem.implicitWidth + leftPadding + rightPadding)
    implicitHeight: 34
    leftPadding: 14
    rightPadding: 14
    topPadding: 0
    bottomPadding: 0

    background: Rectangle {
        radius: Theme.radiusSmall
        color: !control.enabled ? Theme.colorBorder
             : control.pressed ? Qt.darker(control.accentColor, 1.2)
             : control.hovered ? Qt.lighter(control.accentColor, 1.12)
             : control.accentColor
    }

    contentItem: Text {
        text: control.text
        color: control.enabled ? control.textColor : Theme.colorTextMuted
        font.pixelSize: 13
        font.bold: true
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
