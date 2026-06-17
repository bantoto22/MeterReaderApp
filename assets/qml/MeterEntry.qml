import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: meterEntryRoot
    color: "#F8FAFC"

    // Safe bridge reference
    readonly property var bridgeObj: (typeof appBridge !== "undefined" && appBridge) ? appBridge : null

    ScrollView {
        anchors.fill: parent
        contentWidth: parent.width

        ColumnLayout {
            width: parent.width - 32
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: 16
            spacing: 16

            // Search by Meter No. Panel
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: "Search by Meter No."
                    font.pixelSize: 12
                    font.family: "Montserrat"
                    font.bold: true
                    color: "#334155"
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    TextField {
                        id: txtSearch
                        Layout.fillWidth: true
                        placeholderText: "🔍 Type meter no. or name..."
                        text: bridgeObj ? bridgeObj.searchQuery : ""
                        font.pixelSize: 13
                        font.family: "Montserrat"
                        color: "#0F172A"
                        placeholderTextColor: "#94A3B8"
                        padding: 12
                        background: Rectangle {
                            radius: 10
                            border.color: txtSearch.activeFocus ? "#3B82F6" : "#E2E8F0"
                            border.width: txtSearch.activeFocus ? 2 : 1
                            color: txtSearch.activeFocus ? "#FFFFFF" : "#FFFFFF"
                            Behavior on border.color { ColorAnimation { duration: 150 } }
                        }
                        onTextChanged: { if (bridgeObj) bridgeObj.searchQuery = text }
                        onAccepted: { if (bridgeObj) bridgeObj.searchConsumer() }
                    }

                    Button {
                        id: btnSearch
                        implicitWidth: 44
                        implicitHeight: 44
                        scale: btnSearch.pressed ? 0.94 : 1.0
                        Behavior on scale { NumberAnimation { duration: 80 } }

                        contentItem: Text {
                            text: "🔍"
                            font.pixelSize: 16
                            color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: 10
                            color: btnSearch.pressed ? "#1E40AF" : (btnSearch.hovered ? "#2563EB" : "#1D4ED8")
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        onClicked: { if (bridgeObj) bridgeObj.searchConsumer() }
                    }
                }
            }

            // Consumer Details Card
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 410
                radius: 16
                color: "#FFFFFF"
                border.color: "#E2E8F0"
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 14

                    // Consumer Details Header with left blue stripe
                    RowLayout {
                        spacing: 10
                        Rectangle {
                            width: 4
                            height: 18
                            radius: 2
                            color: "#1D4ED8"
                        }
                        Text {
                            text: "Consumer Details"
                            font.pixelSize: 14
                            font.family: "Montserrat"
                            font.bold: true
                            color: "#0F172A"
                        }
                    }

                    // Account No
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Account No."; font.pixelSize: 13; font.family: "Montserrat"; color: "#64748B" }
                        Item { Layout.fillWidth: true }
                        Text { text: bridgeObj ? bridgeObj.accountNo : "-"; font.pixelSize: 13; font.family: "Montserrat"; font.bold: true; color: "#0F172A" }
                    }

                    // Name
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Name"; font.pixelSize: 13; font.family: "Montserrat"; color: "#64748B" }
                        Item { Layout.fillWidth: true }
                        Text { text: bridgeObj ? bridgeObj.consumerName : "-"; font.pixelSize: 13; font.family: "Montserrat"; font.bold: true; color: "#0F172A"; elide: Text.ElideRight; Layout.maximumWidth: 200 }
                    }

                    // Previous
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Previous Reading"; font.pixelSize: 13; font.family: "Montserrat"; color: "#64748B" }
                        Item { Layout.fillWidth: true }
                        Text { text: bridgeObj ? bridgeObj.previousReading : "-"; font.pixelSize: 13; font.family: "Montserrat"; font.bold: true; color: "#0F172A" }
                    }

                    // Separator line
                    Rectangle { Layout.fillWidth: true; height: 1; color: "#F1F5F9" }

                    // Present Reading Header
                    Text {
                        text: "Present Reading"
                        font.pixelSize: 14
                        font.family: "Montserrat"
                        font.bold: true
                        color: "#0F172A"
                    }

                    // Present Reading Entry
                    TextField {
                        id: txtPresent
                        Layout.fillWidth: true
                        placeholderText: "Enter current reading..."
                        text: bridgeObj ? bridgeObj.presentReading : ""
                        font.pixelSize: 15
                        font.family: "Montserrat"
                        color: "#0F172A"
                        placeholderTextColor: "#94A3B8"
                        horizontalAlignment: Text.AlignHCenter
                        padding: 12
                        validator: IntValidator { bottom: 0 }
                        background: Rectangle {
                            radius: 10
                            border.color: txtPresent.activeFocus ? "#3B82F6" : "#E2E8F0"
                            border.width: txtPresent.activeFocus ? 2 : 1
                            color: txtPresent.activeFocus ? "#FFFFFF" : "#F8FAFC"
                            Behavior on border.color { ColorAnimation { duration: 150 } }
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        onTextChanged: { if (bridgeObj) bridgeObj.presentReading = text }
                    }

                    // Consumption calculation display & Badge
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        
                        ColumnLayout {
                            spacing: 2
                            Text {
                                text: "Consumption"
                                font.pixelSize: 13
                                font.family: "Montserrat"
                                font.bold: true
                                color: "#0F172A"
                            }
                            Text {
                                text: {
                                    if (!bridgeObj) return "-";
                                    var cons = bridgeObj.consumption;
                                    return cons === "-" ? "-" : (cons < 0 ? "INVALID READING" : cons + " m³");
                                }
                                font.pixelSize: 14
                                font.family: "Montserrat"
                                font.bold: true
                                color: bridgeObj ? bridgeObj.validationColor : "#64748B"
                            }
                        }

                        Item { Layout.fillWidth: true }

                        // Premium colored badge pill for validation status
                        Rectangle {
                            visible: bridgeObj && bridgeObj.validationMessage !== "-"
                            Layout.preferredWidth: 130
                            Layout.preferredHeight: 30
                            radius: 15
                            color: {
                                var baseCol = bridgeObj ? bridgeObj.validationColor : "#64748B"
                                return baseCol + "1C" // Hex transparency for subtle glass glow
                            }
                            border.color: bridgeObj ? bridgeObj.validationColor : "#64748B"
                            border.width: 1

                            Text {
                                anchors.centerIn: parent
                                text: bridgeObj ? bridgeObj.validationMessage : ""
                                font.pixelSize: 10
                                font.family: "Montserrat"
                                font.bold: true
                                color: bridgeObj ? bridgeObj.validationColor : "#64748B"
                            }
                        }
                    }

                    // Separator line
                    Rectangle { Layout.fillWidth: true; height: 1; color: "#F1F5F9" }

                    // Exception Selector
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Text {
                            text: "Exception"
                            font.pixelSize: 13
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
                                implicitHeight: 40
                                radius: 8
                                border.color: cmbException.focus ? "#3B82F6" : "#E2E8F0"
                                border.width: 1
                                color: "#F8FAFC"
                            }
                            
                            contentItem: Text {
                                text: cmbException.currentText
                                font.family: "Montserrat"
                                font.pixelSize: 13
                                color: "#0F172A"
                                verticalAlignment: Text.AlignVCenter
                                leftPadding: 10
                            }

                            popup: Popup {
                                y: cmbException.height + 2
                                width: cmbException.width
                                implicitHeight: contentItem.implicitHeight
                                padding: 1

                                contentItem: ListView {
                                    clip: true
                                    implicitHeight: contentHeight
                                    model: cmbException.popup.visible ? cmbException.delegateModel : null
                                    currentIndex: cmbException.highlightedIndex

                                    ScrollIndicator.vertical: ScrollIndicator { }
                                }

                                background: Rectangle {
                                    color: "#FFFFFF"
                                    border.color: "#E2E8F0"
                                    border.width: 1
                                    radius: 8
                                }
                            }

                            delegate: ItemDelegate {
                                id: dlg
                                width: cmbException.width
                                contentItem: Text {
                                    text: modelData
                                    font.family: "Montserrat"
                                    font.pixelSize: 13
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

            // PRINT Button (mockup style dark color with hover & click animations)
            Button {
                id: btnPrint
                Layout.fillWidth: true
                implicitHeight: 52
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
                            text: "🖨️"
                            font.pixelSize: 16
                            color: "white"
                            verticalAlignment: Text.AlignVCenter
                        }
                        Text {
                            text: "PRINT"
                            font.bold: true
                            font.family: "Montserrat"
                            color: "white"
                            font.pixelSize: 14
                            font.letterSpacing: 1.5
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
                background: Rectangle {
                    radius: 10
                    color: btnPrint.pressed ? "#0B0F19" : (btnPrint.hovered ? "#334155" : "#1E293B")
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                onClicked: { if (bridgeObj) bridgeObj.printReceipt() }
            }
        }
    }
}
