import QtQuick
import QtQuick.Controls.Basic as Basic
import DcsInstallManager

Basic.ApplicationWindow {
    id: window

    width: 1000
    height: 680
    visible: true
    title: "DCS Install Manager"
    color: Theme.colorBackground

    property string currentView: "catalog" // "catalog" | "rules" | "settings"

    // Blocking first-run step (milestone 5): the normal toolbar/Loader UI is
    // unreachable until a DCS install path is confirmed. Reactive on
    // settingsManager's own property - confirming a path in PathSetupForm unblocks
    // the app immediately, no restart needed.
    readonly property bool firstRunPending: settingsManager.dcsInstallPath.length === 0

    header: Loader {
        active: !window.firstRunPending
        sourceComponent: headerComponent
    }

    Component {
        id: headerComponent
        Rectangle {
            height: 56
            color: Theme.colorSurface

            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: Theme.colorBorder
            }

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Theme.spacingLarge
                Text {
                    text: "DCS Install Manager"
                    color: Theme.colorText
                    font.pixelSize: 17
                    font.bold: true
                }
            }

            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: Theme.spacingLarge
                spacing: Theme.spacingSmall

                FlatButton {
                    text: "Catalog"
                    accentColor: window.currentView === "catalog" ? Theme.colorAccentBlue : Theme.colorBorder
                    textColor: window.currentView === "catalog" ? "white" : Theme.colorText
                    onClicked: window.currentView = "catalog"
                }
                FlatButton {
                    text: "Module Rules"
                    accentColor: window.currentView === "rules" ? Theme.colorAccentBlue : Theme.colorBorder
                    textColor: window.currentView === "rules" ? "white" : Theme.colorText
                    onClicked: window.currentView = "rules"
                }
                FlatButton {
                    text: "Settings"
                    accentColor: window.currentView === "settings" ? Theme.colorAccentBlue : Theme.colorBorder
                    textColor: window.currentView === "settings" ? "white" : Theme.colorText
                    onClicked: window.currentView = "settings"
                }
                FlatButton {
                    text: "Add Entry"
                    visible: window.currentView === "catalog"
                    accentColor: Theme.colorAccentYellow
                    textColor: Theme.colorText
                    onClicked: addEditEntryDialog.openForNew()
                }
                FlatButton {
                    text: "Add Rule"
                    visible: window.currentView === "rules"
                    accentColor: Theme.colorAccentYellow
                    textColor: Theme.colorText
                    onClicked: addEditRuleDialog.openForNew()
                }
            }
        }
    }

    Loader {
        anchors.fill: parent
        sourceComponent: window.firstRunPending ? firstRunComponent
                        : window.currentView === "rules" ? moduleRulesViewComponent
                        : window.currentView === "settings" ? settingsViewComponent
                        : catalogViewComponent
    }

    Component {
        id: firstRunComponent
        Rectangle {
            color: Theme.colorBackground

            PathSetupForm {
                anchors.centerIn: parent
                width: Math.min(560, parent.width - 2 * Theme.spacingLarge)
            }
        }
    }

    Component {
        id: catalogViewComponent
        CatalogView {
            onEditRequested: (entryId) => addEditEntryDialog.openForEdit(entryId)
        }
    }

    Component {
        id: moduleRulesViewComponent
        ModuleRulesView {
            onEditRequested: (ruleId) => addEditRuleDialog.openForEdit(ruleId)
        }
    }

    Component {
        id: settingsViewComponent
        SettingsView {}
    }

    AddEditEntryDialog {
        id: addEditEntryDialog
        parent: window.contentItem
    }

    AddEditRuleDialog {
        id: addEditRuleDialog
        parent: window.contentItem
    }
}
