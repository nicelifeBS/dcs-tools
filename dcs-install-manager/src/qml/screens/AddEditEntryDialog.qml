import QtQuick
import QtQuick.Controls.Basic as Basic
import DcsInstallManager

// Add/edit dialog for one catalog entry. Milestone-4 scope: edits only targets[0]
// (creating it if the entry has none yet) rather than the plan's eventual repeatable
// target block - see the milestone report for why. The underlying targets array is
// otherwise left alone, so a hand-edited multi-target entry in catalog.json is not
// silently truncated by opening it here.
Basic.Dialog {
    id: dialog

    modal: true
    width: 460
    x: (parent ? (parent.width - width) / 2 : 0)
    y: (parent ? Math.max(20, (parent.height - height) / 2) : 0)
    title: isEditMode ? "Edit Entry" : "Add Entry"

    property bool isEditMode: false
    property string editingId: ""
    property bool overrideTarget: false
    property var originalTargets: []
    property var resolvedTarget: ({})

    readonly property var categories: ["aircraft-library", "reinstall-after-update", "livery", "misc"]
    readonly property var locationKinds: ["dcsInstall", "savedGames"]
    readonly property var dcsVariants: ["stable", "openbeta", "any"]

    function indexOfOr(list, value, fallback) {
        const i = list.indexOf(value)
        return i >= 0 ? i : fallback
    }

    function resolveTarget() {
        if (isEditMode)
            return
        const resolved = ruleResolver.resolve(moduleField.text, categoryBox.currentText, nameField.text)
        if (resolved && resolved.relativePath !== undefined && resolved.relativePath !== "") {
            resolvedTarget = resolved
            resolvedLabel.text = "Auto-resolved target: " + resolved.installLocationKind
                                  + " / " + resolved.relativePath
        } else {
            resolvedTarget = {}
            resolvedLabel.text = "No module rule matches yet - set the target manually below."
            overrideTarget = true
        }
    }

    function openForNew() {
        isEditMode = false
        editingId = ""
        originalTargets = []
        overrideTarget = false

        nameField.text = ""
        descriptionField.text = ""
        moduleField.text = ""
        categoryBox.currentIndex = 0
        sourceField.text = ""
        notesField.text = ""
        needsReinstallBox.checked = false
        locationKindBox.currentIndex = 1 // savedGames
        variantBox.currentIndex = 2 // any
        relativePathField.text = ""

        resolveTarget()
        open()
    }

    function openForEdit(entryId) {
        const fields = catalogModel.entryFields(entryId)
        if (!fields || fields.id === undefined)
            return

        isEditMode = true
        editingId = entryId
        overrideTarget = true // editing always shows/edit the real stored target[0]

        nameField.text = fields.name || ""
        descriptionField.text = fields.description || ""
        moduleField.text = fields.module || ""
        categoryBox.currentIndex = indexOfOr(categories, fields.category, 0)
        sourceField.text = (fields.source && fields.source.path) || ""
        notesField.text = fields.notes || ""
        needsReinstallBox.checked = !!fields.needsReinstallAfterUpdate

        originalTargets = fields.targets || []
        const target0 = originalTargets.length > 0 ? originalTargets[0] : {}
        locationKindBox.currentIndex = indexOfOr(locationKinds, target0.installLocationKind, 1)
        variantBox.currentIndex = indexOfOr(dcsVariants, target0.dcsVariant, 2)
        relativePathField.text = target0.relativePath || ""

        resolvedLabel.text = ""
        open()
    }

    function buildTargetsForSave() {
        const fileMappings = (originalTargets.length > 0 && originalTargets[0].fileMappings)
                              ? originalTargets[0].fileMappings : []

        let target0
        if (!isEditMode && !overrideTarget && resolvedTarget.relativePath !== undefined) {
            target0 = resolvedTarget
        } else {
            target0 = {
                installLocationKind: locationKindBox.currentText,
                dcsVariant: variantBox.currentText,
                relativePath: relativePathField.text,
                fileMappings: fileMappings
            }
        }

        if (originalTargets.length === 0)
            return [target0]

        let result = originalTargets.slice()
        result[0] = target0
        return result
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
            name: nameField.text,
            description: descriptionField.text,
            module: moduleField.text,
            category: categoryBox.currentText,
            source: { kind: "folder", path: sourceField.text },
            targets: buildTargetsForSave(),
            needsReinstallAfterUpdate: needsReinstallBox.checked,
            notes: notesField.text
        }

        if (dialog.isEditMode)
            catalogModel.updateEntry(dialog.editingId, fields)
        else
            catalogModel.addEntry(fields)
    }

    contentItem: Basic.ScrollView {
        implicitHeight: Math.min(500, contentHeight)
        contentWidth: availableWidth
        clip: true

        Column {
            width: parent.width
            spacing: Theme.spacingMedium
            padding: Theme.spacingMedium

            Text { text: "Name"; color: Theme.colorTextMuted; font.pixelSize: 12 }
            FlatTextField {
                id: nameField
                width: parent.width - 2 * Theme.spacingMedium
                onTextChanged: dialog.resolveTarget()
            }

            Text { text: "Description"; color: Theme.colorTextMuted; font.pixelSize: 12 }
            FlatTextField {
                id: descriptionField
                width: parent.width - 2 * Theme.spacingMedium
            }

            Row {
                width: parent.width - 2 * Theme.spacingMedium
                spacing: Theme.spacingMedium

                Column {
                    width: (parent.width - Theme.spacingMedium) / 2
                    spacing: Theme.spacingSmall
                    Text { text: "Module"; color: Theme.colorTextMuted; font.pixelSize: 12 }
                    FlatTextField {
                        id: moduleField
                        width: parent.width
                        onTextChanged: dialog.resolveTarget()
                    }
                }
                Column {
                    width: (parent.width - Theme.spacingMedium) / 2
                    spacing: Theme.spacingSmall
                    Text { text: "Category"; color: Theme.colorTextMuted; font.pixelSize: 12 }
                    FlatComboBox {
                        id: categoryBox
                        width: parent.width
                        model: dialog.categories
                        onCurrentTextChanged: dialog.resolveTarget()
                    }
                }
            }

            Text { text: "Source Folder"; color: Theme.colorTextMuted; font.pixelSize: 12 }
            FlatTextField {
                id: sourceField
                width: parent.width - 2 * Theme.spacingMedium
                placeholderText: "C:/path/to/your/mod/folder"
            }

            Rectangle {
                width: parent.width - 2 * Theme.spacingMedium
                height: 1
                color: Theme.colorBorder
            }

            Text {
                text: "Install Target"
                color: Theme.colorText
                font.pixelSize: 13
                font.bold: true
            }

            Text {
                id: resolvedLabel
                width: parent.width - 2 * Theme.spacingMedium
                wrapMode: Text.WordWrap
                color: Theme.colorTextMuted
                font.pixelSize: 12
                visible: !dialog.isEditMode && text.length > 0
            }

            FlatCheckBox {
                id: overrideBox
                text: "Override target"
                visible: !dialog.isEditMode
                checked: dialog.overrideTarget
                onToggled: dialog.overrideTarget = checked
            }

            Row {
                width: parent.width - 2 * Theme.spacingMedium
                spacing: Theme.spacingMedium
                visible: dialog.isEditMode || dialog.overrideTarget

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
                Column {
                    width: (parent.width - Theme.spacingMedium) / 2
                    spacing: Theme.spacingSmall
                    Text { text: "DCS Variant"; color: Theme.colorTextMuted; font.pixelSize: 12 }
                    FlatComboBox {
                        id: variantBox
                        width: parent.width
                        model: dialog.dcsVariants
                    }
                }
            }

            Column {
                width: parent.width - 2 * Theme.spacingMedium
                spacing: Theme.spacingSmall
                visible: dialog.isEditMode || dialog.overrideTarget
                Text { text: "Relative Path"; color: Theme.colorTextMuted; font.pixelSize: 12 }
                FlatTextField {
                    id: relativePathField
                    width: parent.width
                    placeholderText: "Liveries/A-10C II/My Livery"
                }
            }

            Rectangle {
                width: parent.width - 2 * Theme.spacingMedium
                height: 1
                color: Theme.colorBorder
            }

            FlatCheckBox {
                id: needsReinstallBox
                text: "Needs reinstall after DCS update"
            }

            Text { text: "Notes"; color: Theme.colorTextMuted; font.pixelSize: 12 }
            FlatTextField {
                id: notesField
                width: parent.width - 2 * Theme.spacingMedium
            }
        }
    }

    footer: Item {
        implicitHeight: 34 + Theme.spacingMedium * 2
        Row {
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
