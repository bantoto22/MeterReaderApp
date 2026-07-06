import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "TouchMetrics.js" as TouchMetrics

Item {
    id: root
    anchors.left: parent ? parent.left : undefined
    anchors.right: parent ? parent.right : undefined
    anchors.bottom: parent ? parent.bottom : undefined
    z: 1000

    readonly property Item focusedInput: Qt.application.activeWindow ? Qt.application.activeWindow.activeFocusItem : null
    readonly property bool active: isEditableTextInput(focusedInput)
    readonly property string keyboardMode: active && focusedInput.keyboardMode ? focusedInput.keyboardMode : "alpha"
    readonly property bool numericMode: keyboardMode === "numeric"
    property bool shifted: false
    property var alphaRows: [
        ["q","w","e","r","t","y","u","i","o","p"],
        ["a","s","d","f","g","h","j","k","l"],
        ["z","x","c","v","b","n","m"]
    ]
    property var numericRows: [
        ["1", "2", "3"],
        ["4", "5", "6"],
        ["7", "8", "9"],
        [".", "0", "<-"]
    ]

    height: visibleHeight
    visible: active

    readonly property int visibleHeight: active ? (toolbar.height + keyboardBody.height) : 0

    function isEditableTextInput(item) {
        return item
            && item.enabled !== false
            && item.readOnly !== true
            && typeof item.forceActiveFocus === "function"
            && item.hasOwnProperty("text")
            && item.hasOwnProperty("cursorPosition")
    }

    function currentInput() {
        return isEditableTextInput(focusedInput) ? focusedInput : null
    }

    function moveFocus(forward) {
        var current = currentInput()
        if (!current || typeof current.nextItemInFocusChain !== "function")
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

    function hideKeyboard() {
        var current = currentInput()
        if (current && current.hasOwnProperty("focus")) {
            current.focus = false
        }
        root.focus = true
    }

    function canInsert(text) {
        var current = currentInput()
        if (!current || !text || text.length === 0)
            return false
        if (numericMode) {
            if (text === ".") {
                return current.text.indexOf(".") === -1
            }
            return /^[0-9]$/.test(text)
        }
        return true
    }

    function insertText(text) {
        var current = currentInput()
        if (!current || !canInsert(text))
            return

        var toInsert = shifted ? text.toUpperCase() : text
        var start = current.selectionStart
        var end = current.selectionEnd
        if (start !== undefined && end !== undefined && start !== end) {
            current.remove(Math.min(start, end), Math.abs(end - start))
            current.cursorPosition = Math.min(start, end)
        }
        current.insert(current.cursorPosition, toInsert)
        if (shifted && !numericMode)
            shifted = false
    }

    function backspace() {
        var current = currentInput()
        if (!current)
            return
        var start = current.selectionStart
        var end = current.selectionEnd
        if (start !== undefined && end !== undefined && start !== end) {
            current.remove(Math.min(start, end), Math.abs(end - start))
            current.cursorPosition = Math.min(start, end)
            return
        }
        if (current.cursorPosition > 0) {
            current.remove(current.cursorPosition - 1, 1)
        }
    }

    function clearText() {
        var current = currentInput()
        if (current)
            current.text = ""
    }

    function submitOrNext() {
        var current = currentInput()
        if (!current)
            return
        if (typeof current.accepted === "function")
            current.accepted()
        moveFocus(true)
    }

    component KeyboardButton: Button {
        id: control
        property color baseColor: "#FFFFFF"
        property color textColor: "#0F172A"
        property bool specialKey: false
        Layout.fillWidth: true
        implicitHeight: TouchMetrics.keyboardButtonHeight
        contentItem: Text {
            text: control.text
            color: control.textColor
            font.family: "Montserrat"
            font.pixelSize: control.specialKey ? TouchMetrics.keyboardButtonText : 20
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 8
            color: control.pressed ? Qt.darker(control.baseColor, 1.08) : control.baseColor
            border.color: control.specialKey ? "#94A3B8" : "#CBD5E1"
            border.width: 1
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

            KeyboardButton {
                Layout.preferredWidth: 96
                text: "Previous"
                baseColor: "#334155"
                textColor: "white"
                specialKey: true
                onClicked: root.moveFocus(false)
            }

            KeyboardButton {
                Layout.preferredWidth: 84
                text: "Next"
                baseColor: "#334155"
                textColor: "white"
                specialKey: true
                onClicked: root.moveFocus(true)
            }

            KeyboardButton {
                Layout.preferredWidth: 84
                text: "Clear"
                baseColor: "#475569"
                textColor: "white"
                specialKey: true
                onClicked: root.clearText()
            }

            Item { Layout.fillWidth: true }

            KeyboardButton {
                Layout.preferredWidth: 132
                text: "Hide Keyboard"
                baseColor: "#1D4ED8"
                textColor: "white"
                specialKey: true
                onClicked: root.hideKeyboard()
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
        border.color: "#CBD5E1"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: TouchMetrics.keyboardMargin
            spacing: TouchMetrics.keyboardSpacing

            Repeater {
                model: root.numericMode ? root.numericRows : root.alphaRows

                delegate: RowLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignHCenter
                    spacing: TouchMetrics.keyboardSpacing

                    property var keys: modelData

                    Item {
                        visible: !root.numericMode && index === 1
                        Layout.fillWidth: visible
                    }

                    KeyboardButton {
                        visible: !root.numericMode && index === 2
                        Layout.preferredWidth: 78
                        text: root.shifted ? "SHIFT" : "Shift"
                        baseColor: root.shifted ? "#2563EB" : "#E2E8F0"
                        textColor: root.shifted ? "white" : "#0F172A"
                        specialKey: true
                        onClicked: root.shifted = !root.shifted
                    }

                    Repeater {
                        model: keys

                        delegate: KeyboardButton {
                            Layout.preferredWidth: root.numericMode ? 100 : 40
                            text: {
                                if (root.numericMode && modelData === "<-")
                                    return "Back"
                                return root.shifted && !root.numericMode ? modelData.toUpperCase() : modelData
                            }
                            specialKey: root.numericMode && modelData === "<-"
                            baseColor: (root.numericMode && modelData === "<-") ? "#E2E8F0" : "#FFFFFF"
                            onClicked: {
                                if (root.numericMode && modelData === "<-") {
                                    root.backspace()
                                } else {
                                    root.insertText(modelData)
                                }
                            }
                        }
                    }

                    KeyboardButton {
                        visible: !root.numericMode && index === 2
                        Layout.preferredWidth: 94
                        text: "Backspace"
                        baseColor: "#E2E8F0"
                        specialKey: true
                        onClicked: root.backspace()
                    }

                    Item {
                        visible: !root.numericMode && index === 1
                        Layout.fillWidth: visible
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: TouchMetrics.keyboardSpacing

                KeyboardButton {
                    Layout.preferredWidth: 88
                    text: root.numericMode ? "ABC" : "123"
                    baseColor: "#E2E8F0"
                    specialKey: true
                    onClicked: {
                        var current = root.currentInput()
                        if (current && current.hasOwnProperty("keyboardMode")) {
                            current.keyboardMode = root.numericMode ? "alpha" : "numeric"
                            current.forceActiveFocus()
                        }
                    }
                }

                KeyboardButton {
                    visible: !root.numericMode
                    Layout.fillWidth: true
                    text: "Space"
                    baseColor: "#FFFFFF"
                    specialKey: true
                    onClicked: root.insertText(" ")
                }

                KeyboardButton {
                    visible: root.numericMode
                    Layout.fillWidth: true
                    text: "0"
                    baseColor: "#FFFFFF"
                    onClicked: root.insertText("0")
                }

                KeyboardButton {
                    Layout.preferredWidth: 92
                    text: "Enter"
                    baseColor: "#2563EB"
                    textColor: "white"
                    specialKey: true
                    onClicked: root.submitOrNext()
                }
            }
        }
    }
}
