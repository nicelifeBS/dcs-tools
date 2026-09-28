import QtQuick
import QtQuick.Controls.Basic as Basic
import DcsInstallManager

// Table of module rule overrides (module, category, location, path template) with
// Add/Edit/Delete, backed by moduleRuleModel (a QQmlContext property from main.cpp).
Rectangle {
    id: root

    signal editRequested(string ruleId)

    color: Theme.colorBackground

    property string pendingRuleId: ""

    ListView {
        id: listView
        anchors.fill: parent
        anchors.margins: Theme.spacingLarge
        clip: true
        spacing: Theme.spacingSmall
        model: moduleRuleModel

        Basic.ScrollBar.vertical: Basic.ScrollBar {}

        header: Item {
            width: listView.width
            height: 32
            Row {
                anchors.fill: parent
                anchors.leftMargin: Theme.spacingMedium
                spacing: Theme.spacingLarge
                Text { text: "Module"; width: 160; font.bold: true; font.pixelSize: 12; color: Theme.colorTextMuted }
                Text { text: "Category"; width: 150; font.bold: true; font.pixelSize: 12; color: Theme.colorTextMuted }
                Text { text: "Location"; width: 100; font.bold: true; font.pixelSize: 12; color: Theme.colorTextMuted }
                Text { text: "Path Template"; font.bold: true; font.pixelSize: 12; color: Theme.colorTextMuted }
            }
        }

        delegate: Rectangle {
            width: listView.width
            height: 48
            radius: Theme.radiusSmall
            color: Theme.colorSurface
            border.width: 1
            border.color: Theme.colorBorder

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Theme.spacingMedium
                anchors.right: actionsRow.left
                anchors.rightMargin: Theme.spacingMedium
                spacing: Theme.spacingLarge

                Text { text: model.module; width: 160; color: Theme.colorText; elide: Text.ElideRight }
                Text { text: model.category; width: 150; color: Theme.colorText; elide: Text.ElideRight }
                Text { text: model.installLocationKind; width: 100; color: Theme.colorText }
                Text {
                    text: model.pathTemplate
                    color: Theme.colorTextMuted
                    elide: Text.ElideRight
                    width: parent.width - 160 - 150 - 100 - 3 * Theme.spacingLarge
                }
            }

            Row {
                id: actionsRow
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: Theme.spacingMedium
                spacing: Theme.spacingSmall

                FlatButton {
                    text: "Edit"
                    accentColor: Theme.colorBorder
                    textColor: Theme.colorText
                    onClicked: root.editRequested(model.id)
                }
                FlatButton {
                    text: "Delete"
                    accentColor: Theme.colorDanger
                    onClicked: {
                        root.pendingRuleId = model.id
                        confirmDialog.titleText = "Delete Module Rule"
                        confirmDialog.message = "Delete the rule for \"" + model.module
                                                 + " / " + model.category + "\"?"
                        confirmDialog.open()
                    }
                }
            }
        }
    }

    Text {
        anchors.centerIn: parent
        visible: listView.count === 0
        text: "No module rule overrides yet.\nLiveries default to Saved Games unless you add one here."
        horizontalAlignment: Text.AlignHCenter
        color: Theme.colorTextMuted
        font.pixelSize: 14
    }

    ConfirmDialog {
        id: confirmDialog
        parent: root
        onAccepted: moduleRuleModel.removeRule(root.pendingRuleId)
    }
}
