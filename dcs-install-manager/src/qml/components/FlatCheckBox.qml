import QtQuick
import QtQuick.Controls.Basic as Basic
import DcsInstallManager

// Flat, rounded checkbox: a solid-fill square when checked, a bordered square when
// not, with a plain checkmark glyph instead of any icon/animation.
Basic.CheckBox {
    id: control

    font.pixelSize: 13
    implicitHeight: Math.max(24, contentItem.implicitHeight)

    indicator: Rectangle {
        implicitWidth: 20
        implicitHeight: 20
        radius: Theme.radiusSmall
        anchors.verticalCenter: parent.verticalCenter
        color: control.checked ? Theme.colorAccentBlue : Theme.colorSurface
        border.width: 1
        border.color: control.checked ? Theme.colorAccentBlue : Theme.colorBorder

        Text {
            anchors.centerIn: parent
            visible: control.checked
            text: "✓"
            color: "white"
            font.pixelSize: 13
            font.bold: true
        }
    }

    contentItem: Text {
        text: control.text
        color: Theme.colorText
        font: control.font
        leftPadding: control.indicator.width + 8
        verticalAlignment: Text.AlignVCenter
    }
}
