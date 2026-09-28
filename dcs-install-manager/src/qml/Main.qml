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

    property string currentView: "catalog" // "catalog" | "rules"

    header: Rectangle {
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
                text: window.currentView === "catalog" ? "Module Rules" : "Catalog"
                accentColor: Theme.colorAccentBlue
                onClicked: window.currentView = (window.currentView === "catalog" ? "rules" : "catalog")
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

    Loader {
        anchors.fill: parent
        sourceComponent: window.currentView === "catalog" ? catalogViewComponent : moduleRulesViewComponent
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

    AddEditEntryDialog {
        id: addEditEntryDialog
        parent: window.contentItem
    }

    AddEditRuleDialog {
        id: addEditRuleDialog
        parent: window.contentItem
    }
}
