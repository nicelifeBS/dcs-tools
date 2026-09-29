import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Dialogs
import DcsInstallManager

// Shared DCS install path / Saved Games path / library root setup form. Used both as
// the blocking first-run step (Main.qml, when settingsManager.dcsInstallPath is
// empty) and embedded in the ongoing Settings screen (SettingsView.qml), so the same
// component backs both call sites and the path can always be changed later without
// reinstalling the app.
//
// Reads/writes settingsManager directly (a QQmlContext property set in main.cpp)
// rather than round-tripping values through this component's own properties, so both
// call sites and any other future reader of settingsManager always agree.
//
// Native folder-browse dialogs: "import QtQuick.Dialogs" + FolderDialog (Qt 6.3+)
// worked without any friction against this repo's Qt 6.4.2, so that's what Browse
// uses - no text-field fallback was needed. See the milestone-5 report for the one
// packaging caveat (Debian/Ubuntu Qt splits this into its own qml6-module-qtquick-
// dialogs package, not installed by default; MSYS2's mingw-w64-qt6-declarative
// bundles it, so this is expected to just work on the target Windows build).
Rectangle {
    id: root

    radius: Theme.radiusMedium
    color: Theme.colorSurface
    border.width: 1
    border.color: Theme.colorBorder
    implicitHeight: column.implicitHeight + 2 * Theme.spacingLarge

    property var detectedInstalls: []

    // Converts a FolderDialog's selectedFolder (a file:// QUrl) into a plain local
    // path string. Same pattern used in Qt's own FolderDialog/FileDialog examples.
    function urlToLocalPath(url) {
        var s = url.toString()
        s = s.replace(/^file:\/{3}/, "")
        s = s.replace(/^file:\/{2}/, "/")
        return decodeURIComponent(s)
    }

    FolderDialog {
        id: installFolderDialog
        title: "Select DCS Install Folder"
        onAccepted: installPathField.text = root.urlToLocalPath(selectedFolder)
    }
    FolderDialog {
        id: savedGamesFolderDialog
        title: "Select Saved Games Folder"
        onAccepted: savedGamesPathField.text = root.urlToLocalPath(selectedFolder)
    }
    FolderDialog {
        id: libraryRootFolderDialog
        title: "Select Mod Library Root Folder"
        onAccepted: libraryRootPathField.text = root.urlToLocalPath(selectedFolder)
    }

    Column {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Theme.spacingLarge
        spacing: Theme.spacingMedium

        Text {
            text: settingsManager.dcsInstallPath.length === 0
                  ? "Set your DCS install folder to get started."
                  : "DCS Paths"
            color: Theme.colorText
            font.pixelSize: 16
            font.bold: true
            wrapMode: Text.WordWrap
            width: column.width
        }

        Text { text: "DCS Install Folder"; color: Theme.colorTextMuted; font.pixelSize: 12 }
        Row {
            width: column.width
            spacing: Theme.spacingSmall

            FlatTextField {
                id: installPathField
                width: column.width - browseInstallButton.width - validityDot.width - 2 * Theme.spacingSmall
                text: settingsManager.dcsInstallPath
                placeholderText: "C:/Program Files/Eagle Dynamics/DCS World"
            }
            Rectangle {
                id: validityDot
                width: 12
                height: 12
                radius: 6
                anchors.verticalCenter: parent.verticalCenter
                visible: installPathField.text.length > 0
                color: dcsPathLocator.isValidInstallRoot(installPathField.text)
                       ? Theme.colorSuccess : Theme.colorDanger
            }
            FlatButton {
                id: browseInstallButton
                text: "Browse"
                accentColor: Theme.colorBorder
                textColor: Theme.colorText
                onClicked: installFolderDialog.open()
            }
        }
        Text {
            visible: installPathField.text.length > 0 && !dcsPathLocator.isValidInstallRoot(installPathField.text)
            text: "No bin/dcs.exe or bin-mt/dcs.exe found under this folder - double-check it's the DCS install root."
            color: Theme.colorTextMuted
            font.pixelSize: 11
            wrapMode: Text.WordWrap
            width: column.width
        }

        Text { text: "DCS Variant (which one you picked - informational only for now)"; color: Theme.colorTextMuted; font.pixelSize: 12 }
        FlatComboBox {
            id: variantBox
            width: column.width
            model: ["stable", "openbeta"]
            currentIndex: {
                const i = model.indexOf(settingsManager.dcsVariant)
                return i >= 0 ? i : 0
            }
        }

        Text { text: "Saved Games Folder"; color: Theme.colorTextMuted; font.pixelSize: 12 }
        Row {
            width: column.width
            spacing: Theme.spacingSmall

            FlatTextField {
                id: savedGamesPathField
                width: column.width - browseSavedGamesButton.width - Theme.spacingSmall
                text: settingsManager.savedGamesPath
                placeholderText: "C:/Users/you/Saved Games/DCS"
            }
            FlatButton {
                id: browseSavedGamesButton
                text: "Browse"
                accentColor: Theme.colorBorder
                textColor: Theme.colorText
                onClicked: savedGamesFolderDialog.open()
            }
        }

        Text { text: "Mod Library Root (optional)"; color: Theme.colorTextMuted; font.pixelSize: 12 }
        Row {
            width: column.width
            spacing: Theme.spacingSmall

            FlatTextField {
                id: libraryRootPathField
                width: column.width - browseLibraryRootButton.width - Theme.spacingSmall
                text: settingsManager.libraryRootPath
                placeholderText: "C:/Users/you/DCS-ModLibrary"
            }
            FlatButton {
                id: browseLibraryRootButton
                text: "Browse"
                accentColor: Theme.colorBorder
                textColor: Theme.colorText
                onClicked: libraryRootFolderDialog.open()
            }
        }

        Row {
            width: column.width
            spacing: Theme.spacingSmall

            FlatButton {
                text: "Detect Installs"
                accentColor: Theme.colorAccentBlue
                onClicked: root.detectedInstalls = dcsPathLocator.detectInstalls()
            }
            FlatButton {
                text: "Detect Saved Games"
                accentColor: Theme.colorBorder
                textColor: Theme.colorText
                onClicked: {
                    const detected = dcsPathLocator.detectSavedGamesRoot()
                    if (detected.length > 0)
                        savedGamesPathField.text = detected
                }
            }
        }

        Repeater {
            model: root.detectedInstalls
            delegate: Rectangle {
                width: column.width
                height: 34
                radius: Theme.radiusSmall
                color: Theme.colorBackground
                border.width: 1
                border.color: Theme.colorBorder

                Row {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spacingSmall
                    anchors.rightMargin: Theme.spacingSmall
                    spacing: Theme.spacingSmall

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - useButton.width - Theme.spacingSmall
                        text: "[" + modelData.variant + "] " + modelData.path
                        color: Theme.colorText
                        elide: Text.ElideMiddle
                    }
                    FlatButton {
                        id: useButton
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Use"
                        accentColor: Theme.colorAccentYellow
                        textColor: Theme.colorText
                        onClicked: {
                            installPathField.text = modelData.path
                            const i = variantBox.model.indexOf(modelData.variant)
                            if (i >= 0)
                                variantBox.currentIndex = i
                        }
                    }
                }
            }
        }

        Text {
            visible: root.detectedInstalls.length === 0
            text: "No DCS installs auto-detected on this machine. Enter or browse to the path manually."
            color: Theme.colorTextMuted
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            width: column.width
        }

        FlatButton {
            text: settingsManager.dcsInstallPath.length === 0 ? "Confirm" : "Save"
            accentColor: Theme.colorAccentBlue
            enabled: installPathField.text.length > 0
            onClicked: {
                settingsManager.dcsInstallPath = installPathField.text
                settingsManager.dcsVariant = variantBox.currentText
                settingsManager.savedGamesPath = savedGamesPathField.text
                settingsManager.libraryRootPath = libraryRootPathField.text
            }
        }
    }
}
