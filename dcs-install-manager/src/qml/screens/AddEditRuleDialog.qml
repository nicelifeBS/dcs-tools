import QtQuick
import QtQuick.Controls.Basic as Basic
import DcsInstallManager

// Add/edit dialog for one module rule override row.
Basic.Dialog {
    id: dialog

    modal: true
    width: 420
    x: (parent ? (parent.width - width) / 2 : 0)
    y: (parent ? Math.max(20, (parent.height - height) / 2) : 0)
    title: isEditMode ? "Edit Module Rule" : "Add Module Rule"

    property bool isEditMode: false
    property string editingId: ""

    readonly property var categories: ["aircraft-library", "reinstall-after-update", "livery", "misc"]
    readonly property var locationKinds: ["dcsInstall", "savedGames"]
    readonly property var dcsVariants: ["stable", "openbeta", "any"]

    function indexOfOr(list, value, fallback) {
        const i = list.indexOf(value)
        return i >= 0 ? i : fallback
    }

    function openForNew() {
        isEditMode = false
        editingId = ""
        moduleField.text = ""
        categoryBox.currentIndex = 2 // livery
        locationKindBox.currentIndex = 0 // dcsInstall - the typical override case
        variantBox.currentIndex = 2 // any
        pathTemplateField.text = ""
        notesField.text = ""
        open()
    }

    function openForEdit(ruleId) {
        const fields = moduleRuleModel.ruleFields(ruleId)
        if (!fields || fields.id === undefined)
            return

        isEditMode = true
        editingId = ruleId
        moduleField.text = fields.module || ""
        categoryBox.currentIndex = indexOfOr(categories, fields.category, 2)
        locationKindBox.currentIndex = indexOfOr(locationKinds, fields.installLocationKind, 0)
        variantBox.currentIndex = indexOfOr(dcsVariants, fields.dcsVariant, 2)
        pathTemplateField.text = fields.pathTemplate || ""
        notesField.text = fields.notes || ""
        open()
    }

    background: Rectangle {
        radius: Theme.radiusMedium
        color: Theme.colorSurface
        border.width: 1
        border.color: Theme.colorBorder
    }

    header: Text {
        text: dialog.title
        color: Theme.colorText
        font.pixelSize: 16
        font.bold: true
        padding: Theme.spacingMedium
        bottomPadding: 0
    }

    onAccepted: {
        const fields = {
            module: moduleField.text,
            category: categoryBox.currentText,
            installLocationKind: locationKindBox.currentText,
            dcsVariant: variantBox.currentText,
            pathTemplate: pathTemplateField.text,
            notes: notesField.text
        }

        if (dialog.isEditMode)
            moduleRuleModel.updateRule(dialog.editingId, fields)
        else
            moduleRuleModel.addRule(fields)
    }

    contentItem: Column {
        width: parent.width
        spacing: Theme.spacingMedium
        padding: Theme.spacingMedium

        Text { text: "Module"; color: Theme.colorTextMuted; font.pixelSize: 12 }
        FlatTextField {
            id: moduleField
            width: parent.width - 2 * Theme.spacingMedium
            placeholderText: "A-10C II"
        }

        Row {
            width: parent.width - 2 * Theme.spacingMedium
            spacing: Theme.spacingMedium

            Column {
                width: (parent.width - Theme.spacingMedium) / 2
                spacing: Theme.spacingSmall
                Text { text: "Category"; color: Theme.colorTextMuted; font.pixelSize: 12 }
                FlatComboBox {
                    id: categoryBox
                    width: parent.width
                    model: dialog.categories
                }
            }
            Column {
                width: (parent.width - Theme.spacingMedium) / 2
                spacing: Theme.spacingSmall
                Text { text: "Location"; color: Theme.colorTextMuted; font.pixelSize: 12 }
                FlatComboBox {
                    id: locationKindBox
                    width: parent.width
                    model: dialog.locationKinds
                }
            }
        }

        Text { text: "DCS Variant"; color: Theme.colorTextMuted; font.pixelSize: 12 }
        FlatComboBox {
            id: variantBox
            width: parent.width - 2 * Theme.spacingMedium
            model: dialog.dcsVariants
        }

        Text { text: "Path Template"; color: Theme.colorTextMuted; font.pixelSize: 12 }
        FlatTextField {
            id: pathTemplateField
            width: parent.width - 2 * Theme.spacingMedium
            placeholderText: "Bazar/Liveries/{module}/{entryName}"
        }

        Text { text: "Notes"; color: Theme.colorTextMuted; font.pixelSize: 12 }
        FlatTextField {
            id: notesField
            width: parent.width - 2 * Theme.spacingMedium
        }
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
                accentColor: Theme.colorBorder
                textColor: Theme.colorText
                onClicked: dialog.reject()
            }
            FlatButton {
                text: "Save"
                accentColor: Theme.colorAccentBlue
                onClicked: dialog.accept()
            }
        }
    }
}
