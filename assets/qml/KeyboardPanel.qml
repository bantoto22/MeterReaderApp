import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.VirtualKeyboard
import "TouchMetrics.js" as TouchMetrics

Item {
    id: root
    anchors.left: parent ? parent.left : undefined
    anchors.right: parent ? parent.right : undefined
    anchors.bottom: parent ? parent.bottom : undefined
    z: 1000

    readonly property bool active: inputPanel.active
    readonly property int visibleHeight: active ? (toolbar.height + keyboardBody.height) : 0
    readonly property Item focusedInput: Qt.application.activeWindow ? Qt.application.activeWindow.activeFocusItem : null

    height: visibleHeight
    visible: active

    function isEditableTextInput(item) {
        return item
            && item.enabled !== false
            && item.readOnly !== true
            && typeof item.forceActiveFocus === "function"
            && item.hasOwnProperty("cursorPosition")
    }

    function moveFocus(forward) {
        var current = focusedInput
        if (!isEditableTextInput(current) || typeof current.nextItemInFocusChain !== "function")
            return

        var next = current.nextItemInFocusChain(forward)
        while (next && next !== current) {
            if (isEditableTextInput(next)) {
                next.forceActiveFocus(Qt.TabFocusReason)
                return
            }
            if (typeof next.nextItemInFocusChain !== "function")
                break
            next = next.nextItemInFocusChain(forward)
        }
    }

    component KeyboardActionButton: Button {
        id: control
        implicitHeight: TouchMetrics.keyboardButtonHeight
        contentItem: Text {
            text: control.text
            color: "white"
            font.family: "Montserrat"
            font.pixelSize: TouchMetrics.keyboardButtonText
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 8
            color: control.pressed ? "#1D4ED8" : (control.hovered ? "#2563EB" : "#334155")
        }
    }

    Rectangle {
        id: toolbar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: TouchMetrics.keyboardAccessoryHeight
        color: "#111827"
        border.color: "#334155"

        RowLayout {
            anchors.fill: parent
            anchors.margins: TouchMetrics.keyboardMargin
            spacing: TouchMetrics.keyboardSpacing

            KeyboardActionButton {
                Layout.preferredWidth: 96
                text: "Previous"
                enabled: root.isEditableTextInput(root.focusedInput)
                onClicked: root.moveFocus(false)
            }

            KeyboardActionButton {
                Layout.preferredWidth: 84
                text: "Next"
                enabled: root.isEditableTextInput(root.focusedInput)
                onClicked: root.moveFocus(true)
            }

            Item { Layout.fillWidth: true }

            KeyboardActionButton {
                Layout.preferredWidth: 112
                text: "Hide Keyboard"
                onClicked: Qt.inputMethod.hide()
            }
        }
    }

    Rectangle {
        id: keyboardBody
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: toolbar.bottom
        height: root.width <= 420 ? TouchMetrics.compactKeyboardHeight : TouchMetrics.keyboardHeight
        color: "#DDE7F2"

        InputPanel {
            id: inputPanel
            anchors.fill: parent
        }
    }
}
