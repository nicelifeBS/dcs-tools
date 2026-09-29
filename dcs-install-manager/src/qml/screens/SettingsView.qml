import QtQuick
import QtQuick.Controls.Basic as Basic
import DcsInstallManager

// Ongoing Settings screen, reachable from the toolbar once past first run. Reuses the
// exact same PathSetupForm used for the blocking first-run step in Main.qml, so the
// DCS install/Saved Games/library-root paths can always be changed later.
Rectangle {
    id: root

    color: Theme.colorBackground

    Basic.ScrollView {
        anchors.fill: parent
        anchors.margins: Theme.spacingLarge
        clip: true

        Basic.ScrollBar.vertical: Basic.ScrollBar {}

        PathSetupForm {
            width: Math.min(640, root.width - 2 * Theme.spacingLarge)
        }
    }
}
