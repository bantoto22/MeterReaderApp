import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "TouchMetrics.js" as TouchMetrics

Rectangle {
    id: meterEntryRoot
    color: "#F8FAFC"

    readonly property var bridgeObj: (typeof appBridge !== "undefined" && appBridge) ? appBridge : null
    readonly property bool showSuggestions: bridgeObj && bridgeObj.searchSuggestions && bridgeObj.searchSuggestions.length > 0
    readonly property bool compactScreen: width <= 420
    readonly property var currentConsumption: {
        if (!bridgeObj || bridgeObj.consumption === "-") return 0
        return parseFloat(bridgeObj.consumption)
    }

    function showPrintAlert(title, message) {
        printAlertDialog.title = title
        printAlertText.text = message
        printAlertDialog.open()
    }

    function requestPrint() {
        if (!bridgeObj) return
        if (bridgeObj.accountNo === "-" || bridgeObj.consumerName === "-" || bridgeObj.consumerName === "Consumer not found") {
            showPrintAlert("Select Consumer", "Please select a consumer before printing.")
            return
        }
        if (bridgeObj.presentReading.length === 0) {
            showPrintAlert("Missing Reading", "Please enter the present reading before printing.")
            return
        }
        if (bridgeObj.consumption === "-" || isNaN(currentConsumption)) {
            showPrintAlert("Invalid Details", "Please complete the meter details before printing.")
            return
        }
        if (currentConsumption < 0) {
            showPrintAlert("Invalid Consumption", "Present reading cannot be lower than the previous reading.")
            return
        }
        var paper = bridgeObj.paperStatus.toLowerCase()
        if (paper === "out" || paper === "jam") {
            showPrintAlert("Paper Error", "Cannot print while paper status is " + bridgeObj.paperStatus + ".")
            return
        }
        if (paper === "low") {
            paperLowDialog.open()
            return
        }
        continuePrintValidation()
    }

    function continuePrintValidation() {
        if (currentConsumption > 500) {
            highConsumptionDialog.open()
            return
        }
        bridgeObj.printReceipt()
    }

    Dialog {
        id: paperLowDialog
        title: "Paper Low"
        modal: true
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 340)
        standardButtons: Dialog.Yes | Dialog.No
        onAccepted: continuePrintValidation()
        contentItem: Text { text: "Paper is running low. Continue printing?"; wrapMode: Text.WordWrap; color: "#111827"; font.family: "Montserrat" }
        background: Rectangle { color: "white"; radius: 8; border.color: "#D8E1EC" }
    }

    Dialog {
        id: highConsumptionDialog
        title: "High Consumption Warning"
        modal: true
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 360)
        standardButtons: Dialog.Yes | Dialog.No
        onAccepted: bridgeObj.printReceipt()
        contentItem: Text { text: "Consumption is unusually high. Continue printing?"; wrapMode: Text.WordWrap; color: "#111827"; font.family: "Montserrat" }
        background: Rectangle { color: "white"; radius: 8; border.color: "#D8E1EC" }
    }

    Dialog {
        id: printAlertDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 320)
        standardButtons: Dialog.Ok

        contentItem: Text {
            id: printAlertText
            width: parent.width
            wrapMode: Text.WordWrap
            color: "#0F172A"
            font.family: "Montserrat"
            font.pixelSize: 12
        }

        background: Rectangle {
            color: "white"
            radius: 8
            border.color: "#CBD5E1"
            border.width: 1
        }
    }

    ScrollablePage {
        anchors.fill: parent
        maxContentWidth: 440

        ColumnLayout {
            Layout.fillWidth: true
            spacing: TouchMetrics.sectionSpacing

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Search by Meter No."
                        font.pixelSize: TouchMetrics.bodyText
                        font.family: "Montserrat"
                        font.bold: true
                        color: "#111827"
                    }
                    Item { Layout.fillWidth: true }
                    ComboBox {
                        id: cmbEntryZone
                        Layout.preferredWidth: Math.min(210, meterEntryRoot.width * 0.42)
                        model: bridgeObj ? bridgeObj.zones : []
                        currentIndex: bridgeObj ? Math.max(0, bridgeObj.zones.indexOf(bridgeObj.selectedZone)) : 0
                        background: Rectangle { implicitHeight: TouchMetrics.inputHeight; radius: 7; color: "#2563EB" }
                        contentItem: Text { text: cmbEntryZone.currentText; color: "white"; font.family: "Montserrat"; font.pixelSize: TouchMetrics.bodyText; font.bold: true; verticalAlignment: Text.AlignVCenter; leftPadding: 12 }
                        onActivated: { if (bridgeObj && currentText) bridgeObj.selectedZone = currentText }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        TextField {
                            id: txtSearch
                            property string keyboardMode: "alpha"
                            Layout.fillWidth: true
                            placeholderText: "Type 001, 002..."
                            text: bridgeObj ? bridgeObj.searchQuery : ""
                            inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhPreferLowercase
                            font.pixelSize: TouchMetrics.bodyText
                            font.family: "Montserrat"
                            color: "#0F172A"
                            placeholderTextColor: "#94A3B8"
                            padding: 12
                            background: Rectangle {
                                radius: 8
                                border.color: txtSearch.activeFocus ? "#3B82F6" : "#E2E8F0"
                                border.width: txtSearch.activeFocus ? 2 : 1
                                color: "#FFFFFF"
                                Behavior on border.color { ColorAnimation { duration: 150 } }
                            }
                            onTextChanged: { if (bridgeObj) bridgeObj.searchQuery = text }
                            onAccepted: { if (bridgeObj) bridgeObj.searchConsumer() }
                        }

                        Popup {
                            id: searchPopup
                            visible: showSuggestions && txtSearch.length > 0 && txtSearch.activeFocus
                            x: txtSearch.x
                            y: txtSearch.height + 4
                            width: txtSearch.width
                            padding: 0
                            focus: false

                            background: Rectangle {
                                radius: 8
                                color: "white"
                                border.color: "#E2E8F0"
                                border.width: 1
                            }

                            contentItem: ListView {
                                clip: true
                                implicitHeight: Math.min(contentHeight, 240)
                                model: bridgeObj ? bridgeObj.searchSuggestions : []

                                delegate: ItemDelegate {
                                    id: suggestionDelegate
                                    width: searchPopup.width
                                    contentItem: Text {
                                        text: modelData.meter_no + " - " + modelData.name
                                        color: "#0F172A"
                                        font.family: "Montserrat"
                                        font.pixelSize: 13
                                        elide: Text.ElideRight
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    background: Rectangle {
                                        color: suggestionDelegate.hovered ? "#EFF6FF" : "white"
                                    }
                                    onClicked: {
                                        if (bridgeObj) bridgeObj.selectSearchSuggestion(modelData.meter_no)
                                        searchPopup.close()
                                    }
                                }
                            }
                        }
                    }

                    Button {
                        id: btnSearch
                        implicitWidth: TouchMetrics.iconButtonSize
                        implicitHeight: TouchMetrics.iconButtonSize
                        scale: btnSearch.pressed ? 0.94 : 1.0
                        Behavior on scale { NumberAnimation { duration: 80 } }

                        contentItem: Text {
                            text: "Go"
                            font.pixelSize: TouchMetrics.helperText
                            font.family: "Montserrat"
                            font.bold: true
                            color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: 8
                            color: btnSearch.pressed ? "#1E40AF" : (btnSearch.hovered ? "#2563EB" : "#1D4ED8")
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        onClicked: { if (bridgeObj) bridgeObj.searchConsumer() }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: detailsColumn.implicitHeight + (meterEntryRoot.compactScreen ? 28 : 40)
                radius: 8
                color: "#FFFFFF"
                border.color: "#E2E8F0"
                border.width: 1

                ColumnLayout {
                    id: detailsColumn
                    anchors.fill: parent
                    anchors.margins: meterEntryRoot.compactScreen ? 14 : 20
                    spacing: meterEntryRoot.compactScreen ? 12 : 14

                    RowLayout {
                        spacing: 10
                        Rectangle { width: 4; height: 18; radius: 2; color: "#1D4ED8" }
                        Text {
                            text: "Consumer Details"
                            font.pixelSize: TouchMetrics.sectionTitle
                            font.family: "Montserrat"
                            font.bold: true
                            color: "#0F172A"
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Account No."; font.pixelSize: TouchMetrics.bodyText; font.family: "Montserrat"; color: "#64748B" }
                        Item { Layout.fillWidth: true }
                        Text { text: bridgeObj ? bridgeObj.accountNo : "-"; font.pixelSize: TouchMetrics.bodyText; font.family: "Montserrat"; font.bold: true; color: "#0F172A" }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Name"; font.pixelSize: TouchMetrics.bodyText; font.family: "Montserrat"; color: "#64748B" }
                        Item { Layout.fillWidth: true }
                        Text { text: bridgeObj ? bridgeObj.consumerName : "-"; font.pixelSize: TouchMetrics.bodyText; font.family: "Montserrat"; font.bold: true; color: "#0F172A"; elide: Text.ElideRight; Layout.maximumWidth: 220 }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Previous Reading"; font.pixelSize: TouchMetrics.bodyText; font.family: "Montserrat"; color: "#64748B" }
                        Item { Layout.fillWidth: true }
                        Text { text: bridgeObj ? bridgeObj.previousReading : "-"; font.pixelSize: TouchMetrics.bodyText; font.family: "Montserrat"; font.bold: true; color: "#0F172A" }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: "#F1F5F9" }

                    Text {
                        text: "Present Reading"
                        font.pixelSize: TouchMetrics.sectionTitle
                        font.family: "Montserrat"
                        font.bold: true
                        color: "#0F172A"
                    }

                    TextField {
                        id: txtPresent
                        property string keyboardMode: "numeric"
                        Layout.fillWidth: true
                        placeholderText: "Enter current reading..."
                        text: bridgeObj ? bridgeObj.presentReading : ""
                        inputMethodHints: Qt.ImhFormattedNumbersOnly | Qt.ImhNoPredictiveText
                        font.pixelSize: 18
                        font.family: "Montserrat"
                        color: "#0F172A"
                        placeholderTextColor: "#94A3B8"
                        horizontalAlignment: Text.AlignHCenter
                        padding: 12
                        validator: DoubleValidator {
                            bottom: 0
                            decimals: 2
                            notation: DoubleValidator.StandardNotation
                        }
                        background: Rectangle {
                            radius: 8
                            border.color: txtPresent.activeFocus ? "#3B82F6" : "#E2E8F0"
                            border.width: txtPresent.activeFocus ? 2 : 1
                            color: txtPresent.activeFocus ? "#FFFFFF" : "#F8FAFC"
                            Behavior on border.color { ColorAnimation { duration: 150 } }
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        onTextChanged: { if (bridgeObj) bridgeObj.presentReading = text }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        ColumnLayout {
                            spacing: 2
                            Text {
                                text: "Consumption"
                                font.pixelSize: TouchMetrics.bodyText
                                font.family: "Montserrat"
                                font.bold: true
                                color: "#0F172A"
                            }
                            Text {
                                text: {
                                    if (!bridgeObj) return "-"
                                    var cons = bridgeObj.consumption
                                    return cons === "-" ? "-" : (cons < 0 ? "INVALID READING" : cons + " m³")
                                }
                                font.pixelSize: 18
                                font.family: "Montserrat"
                                font.bold: true
                                color: bridgeObj ? bridgeObj.validationColor : "#64748B"
                                wrapMode: Text.WordWrap
                                maximumLineCount: 2
                            }
                        }

                        Item { Layout.fillWidth: true }

                        Rectangle {
                            visible: bridgeObj && bridgeObj.validationMessage !== "-"
                            Layout.minimumWidth: 130
                            Layout.maximumWidth: 260
                            Layout.preferredHeight: 30
                            radius: 15
                            color: {
                                var baseCol = bridgeObj ? bridgeObj.validationColor : "#64748B"
                                return baseCol + "1C"
                            }
                            border.color: bridgeObj ? bridgeObj.validationColor : "#64748B"
                            border.width: 1

                            Text {
                                anchors.fill: parent
                                anchors.margins: 8
                                text: bridgeObj ? bridgeObj.validationMessage : ""
                                font.pixelSize: TouchMetrics.helperText
                                font.family: "Montserrat"
                                font.bold: true
                                color: bridgeObj ? bridgeObj.validationColor : "#64748B"
                                elide: Text.ElideRight
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: "#F1F5F9" }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Text {
                            text: "Exception"
                            font.pixelSize: TouchMetrics.bodyText
                            font.family: "Montserrat"
                            font.bold: true
                            color: "#0F172A"
                        }

                        ComboBox {
                            id: cmbException
                            Layout.fillWidth: true
                            model: bridgeObj ? bridgeObj.exceptions : []
                            currentIndex: bridgeObj ? Math.max(0, bridgeObj.exceptions.indexOf(bridgeObj.selectedException)) : 0

                            background: Rectangle {
                                implicitHeight: TouchMetrics.inputHeight
                                radius: 8
                                border.color: cmbException.focus ? "#3B82F6" : "#E2E8F0"
                                border.width: 1
                                color: "#F8FAFC"
                            }

                            contentItem: Text {
                                text: cmbException.currentText
                                font.family: "Montserrat"
                                font.pixelSize: TouchMetrics.bodyText
                                color: "#0F172A"
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 10
                            }

                            delegate: ItemDelegate {
                                id: dlg
                                width: cmbException.width
                                contentItem: Text {
                                    text: modelData
                                    font.family: "Montserrat"
                                    font.pixelSize: TouchMetrics.bodyText
                                    color: dlg.highlighted ? "#FFFFFF" : "#0F172A"
                                    verticalAlignment: Text.AlignVCenter
                                }
                                background: Rectangle {
                                    color: dlg.highlighted ? "#3B82F6" : "transparent"
                                    radius: 4
                                }
                                highlighted: cmbException.highlightedIndex === index
                            }

                            onCurrentTextChanged: {
                                if (bridgeObj && currentText) {
                                    bridgeObj.selectedException = currentText
                                }
                            }
                        }
                    }
                }
            }

            Button {
                id: btnPrint
                Layout.fillWidth: true
                implicitHeight: 56
                scale: btnPrint.pressed ? 0.96 : 1.0
                Behavior on scale { NumberAnimation { duration: 80 } }

                contentItem: Item {
                    implicitWidth: printRow.implicitWidth
                    implicitHeight: printRow.implicitHeight
                    Row {
                        id: printRow
                        anchors.centerIn: parent
                        spacing: 8
                        Text {
                            text: ""
                            font.pixelSize: 1
                            color: "white"
                            verticalAlignment: Text.AlignVCenter
                        }
                        Text {
                            text: "PRINT"
                            font.bold: true
                            font.family: "Montserrat"
                            color: "white"
                            font.pixelSize: TouchMetrics.buttonText
                            font.letterSpacing: 1.5
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
                background: Rectangle {
                    radius: 8
                    color: btnPrint.pressed ? "#0B0F19" : (btnPrint.hovered ? "#334155" : "#1E293B")
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                onClicked: requestPrint()
            }

            Button {
                id: btnReprint
                Layout.fillWidth: true
                implicitHeight: TouchMetrics.buttonHeight
                enabled: bridgeObj ? bridgeObj.canReprint : false
                contentItem: Text {
                    text: "Reprint Last Receipt"
                    color: btnReprint.enabled ? "#2563EB" : "#94A3B8"
                    font.family: "Montserrat"
                    font.pixelSize: TouchMetrics.buttonText
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle { radius: 8; color: btnReprint.hovered ? "#DBEAFE" : "#EFF6FF"; border.color: "#BFDBFE" }
                onClicked: { if (bridgeObj) bridgeObj.reprintLastReceipt() }
            }

            Button {
                Layout.fillWidth: true
                implicitHeight: TouchMetrics.buttonHeight
                contentItem: Text {
                    text: "Print History"
                    color: "#0F766E"
                    font.family: "Montserrat"
                    font.pixelSize: TouchMetrics.buttonText
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle { radius: 8; color: "#ECFDF5"; border.color: "#A7F3D0" }
                onClicked: { if (bridgeObj) bridgeObj.openPrintHistory() }
            }

            RowLayout {
                Layout.fillWidth: true
                Text { text: "Paper Status (Test):"; color: "#526176"; font.family: "Montserrat"; font.pixelSize: TouchMetrics.helperText }
                Item { Layout.fillWidth: true }
                Repeater {
                    model: ["OK", "Low", "Out", "Jam"]
                    Button {
                        implicitWidth: 64
                        implicitHeight: 40
                        contentItem: Text {
                            text: modelData
                            font.family: "Montserrat"
                            font.pixelSize: TouchMetrics.helperText
                            font.bold: true
                            color: modelData === "OK" ? "#10B981" : (modelData === "Low" ? "#F59E0B" : "#EF4444")
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle { radius: 6; color: parent.hovered ? "#E2E8F0" : "transparent" }
                        onClicked: { if (bridgeObj) bridgeObj.setPaperStatus(modelData) }
                    }
                }
            }
        }
    }
}
