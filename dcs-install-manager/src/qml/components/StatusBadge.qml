import QtQuick
import DcsInstallManager

// Simple two-state "Installed" / "Not Installed" badge (milestone 4 scope - the
// plan's eventual multi-state drift status enum arrives with DriftChecker in
// milestone 6).
Rectangle {
    id: badge

    property bool installed: false

    radius: Theme.radiusSmall
    color: installed ? Theme.colorSuccess : Theme.colorBorder
    implicitWidth: label.implicitWidth + 16
    implicitHeight: label.implicitHeight + 6

    Text {
        id: label
        anchors.centerIn: parent
        text: badge.installed ? "Installed" : "Not Installed"
        color: badge.installed ? "white" : Theme.colorText
        font.pixelSize: 11
        font.bold: true
    }
}
