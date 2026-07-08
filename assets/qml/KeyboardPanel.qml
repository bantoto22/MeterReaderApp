import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "TouchMetrics.js" as TouchMetrics

Item {
    id: root
    anchors.left: parent ? parent.left : undefined
    anchors.right: parent ? parent.right : undefined
    anchors.bottom: parent ? parent.bottom : undefined
    z: 1000

    readonly property var hostWindow: root.Window.window
    readonly property Item focusedInput: hostWindow && hostWindow.activeFocusItem ? hostWindow.activeFocusItem : null
    readonly property bool active: isEditableTextInput(focusedInput)
    readonly property string activeMode: active && focusedInput.keyboardMode ? focusedInput.keyboardMode : "alpha"
    property string viewMode: activeMode === "numeric" ? "numeric" : "alpha"
    property bool shifted: false

    onActiveModeChanged: {
        viewMode = activeMode === "numeric" ? "numeric" : "alpha"
    }

    property var alphaRows: [
        ["1","2","3","4","5","6","7","8","9","0"],
        ["q","w","e","r","t","y","u","i","o","p"],
        ["a","s","d","f","g","h","j","k","l"],
        ["⇧","z","x","c","v","b","n","m","⌫"],
        ["?123",",","Space",".","→"]
    ]
    
    property var symbolRows: [
        ["1","2","3","4","5","6","7","8","9","0"],
        ["@","#","$","_","&","-","+","(",")","/"],
        ["=\\<","*","\"","'",":",";","!","?","⌫"],
        ["ABC",",","Space",".","→"]
    ]
    
    property var numericRows: [
        ["1", "2", "3"],
        ["4", "5", "6"],
        ["7", "8", "9"],
        ["-", ".", "0", "⌫"],
        ["ABC", "Space", "→"]
    ]

    height: visibleHeight
    visible: active

    readonly property int visibleHeight: active ? keyboardBody.height : 0

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
        if (activeMode === "numeric") {
            if (text === "-") {
                return current.cursorPosition === 0 && current.text.indexOf("-") === -1
            }
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
            current.remove(Math.min(start, end), Math.max(start, end))
            current.cursorPosition = Math.min(start, end)
        }
        current.insert(current.cursorPosition, toInsert)
        if (shifted && viewMode === "alpha")
            shifted = false
    }

    function backspace() {
        var current = currentInput()
        if (!current)
            return
        var start = current.selectionStart
        var end = current.selectionEnd
        if (start !== undefined && end !== undefined && start !== end) {
            current.remove(Math.min(start, end), Math.max(start, end))
            current.cursorPosition = Math.min(start, end)
            return
        }
        if (current.cursorPosition > 0) {
            current.remove(current.cursorPosition - 1, current.cursorPosition)
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
        if (current.hasOwnProperty("accepted")) {
            try {
                current.accepted()
                return
            } catch (error) {
            }
        }
        moveFocus(true)
    }

    component KeyboardButton: Button {
        id: control
        property color baseColor: "#FFFFFF"
        property color textColor: "#0F172A"
        property bool specialKey: false
        focusPolicy: Qt.NoFocus
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
        id: keyboardBody
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: (root.width <= 420 ? TouchMetrics.compactKeyboardHeight : TouchMetrics.keyboardHeight) + 40
        color: "#DDE7F2"
        border.color: "#CBD5E1"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: TouchMetrics.keyboardMargin
            spacing: TouchMetrics.keyboardSpacing

            Repeater {
                model: {
                    if (root.viewMode === "numeric") return root.numericRows;
                    if (root.viewMode === "symbols") return root.symbolRows;
                    return root.alphaRows;
                }

                delegate: RowLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignHCenter
                    spacing: TouchMetrics.keyboardSpacing

                    property var keys: modelData
                    property int rowIndex: index

                    // Spacer for middle alpha row to center it properly
                    Item {
                        visible: (root.viewMode === "alpha" && rowIndex === 2)
                        Layout.fillWidth: visible
                    }

                    Repeater {
                        model: keys

                        delegate: KeyboardButton {
                            // Let regular keys stretch but spacebar and special keys have specific behaviors
                            Layout.fillWidth: (modelData === "Space" || (modelData !== "Space" && !specialKey))
                            Layout.preferredWidth: {
                                if (modelData === "Space") return -1;
                                if (["⇧", "⌫", "?123", "ABC", "=\\<", "→"].includes(modelData)) return 60;
                                return 40;
                            }
                            
                            text: {
                                if (modelData === "Space") return "Space";
                                if (root.viewMode === "alpha" && root.shifted && modelData.length === 1 && modelData.match(/[a-z]/i)) {
                                    return modelData.toUpperCase();
                                }
                                return modelData;
                            }
                            
                            specialKey: ["⇧", "⌫", "?123", "ABC", "=\\<", "→", "Space"].includes(modelData)
                            baseColor: {
                                if (modelData === "⇧" && root.shifted) return "#2563EB";
                                if (modelData === "→") return "#2563EB";
                                if (specialKey && modelData !== "Space") return "#E2E8F0";
                                return "#FFFFFF";
                            }
                            textColor: {
                                if (modelData === "⇧" && root.shifted) return "white";
                                if (modelData === "→") return "white";
                                return "#0F172A";
                            }
                            
                            onClicked: {
                                if (modelData === "⇧") {
                                    root.shifted = !root.shifted;
                                } else if (modelData === "⌫") {
                                    root.backspace();
                                } else if (modelData === "?123") {
                                    root.viewMode = "symbols";
                                } else if (modelData === "ABC") {
                                    root.viewMode = "alpha";
                                } else if (modelData === "=\\<") {
                                    // Placeholder for additional symbols
                                } else if (modelData === "→") {
                                    root.submitOrNext();
                                } else if (modelData === "Space") {
                                    root.insertText(" ");
                                } else {
                                    root.insertText(root.shifted && root.viewMode === "alpha" ? modelData.toUpperCase() : modelData);
                                }
                            }
                        }
                    }

                    // Spacer for middle alpha row
                    Item {
                        visible: (root.viewMode === "alpha" && rowIndex === 2)
                        Layout.fillWidth: visible
                    }
                }
            }

            // Bottom accessory bar for hide keyboard button and home indicator
            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: 32
                
                Button {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: 48
                    height: 32
                    text: "﹀"
                    focusPolicy: Qt.NoFocus
                    background: Item {} // Transparent background
                    contentItem: Text {
                        text: parent.text
                        color: "#0F172A"
                        font.pixelSize: 24
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: root.hideKeyboard()
                }
                
                Rectangle {
                    anchors.centerIn: parent
                    width: 120
                    height: 4
                    radius: 2
                    color: "#94A3B8"
                }
            }
        }
    }
}
