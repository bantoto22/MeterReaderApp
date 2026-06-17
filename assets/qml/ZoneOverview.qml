import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: progressRoot
    color: "#F8FAFC"

    // Safe bridge reference
    readonly property var bridgeObj: (typeof appBridge !== "undefined" && appBridge) ? appBridge : null
    readonly property real compPercent: bridgeObj ? bridgeObj.zoneCompletionPercentage : 0.0

    ScrollView {
        anchors.fill: parent
        contentWidth: parent.width

        ColumnLayout {
            width: parent.width - 32
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: 16
            spacing: 16

            // Assigned Zone Section
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6

                Text {
                    text: "Assigned Zone"
                    font.pixelSize: 12
                    font.family: "Montserrat"
                    font.bold: true
                    color: "#334155"
                }

                ComboBox {
                    id: cmbProgressZone
                    Layout.fillWidth: true
                    model: bridgeObj ? bridgeObj.zones : []
                    currentIndex: bridgeObj ? Math.max(0, bridgeObj.zones.indexOf(bridgeObj.selectedZone)) : 0
                    
                    background: Rectangle {
                        implicitHeight: 40
                        radius: 8
                        border.color: cmbProgressZone.focus ? "#3B82F6" : "#E2E8F0"
                        border.width: 1
                        color: "#F8FAFC"
                    }
                    
                    contentItem: Text {
                        text: cmbProgressZone.currentText
                        font.family: "Montserrat"
                        font.pixelSize: 13
                        color: "#0F172A"
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 10
                    }

                    popup: Popup {
                        id: cmbPopup
                        y: cmbProgressZone.height + 2
                        width: cmbProgressZone.width
                        implicitHeight: contentItem.implicitHeight
                        padding: 1

                        contentItem: ListView {
                            clip: true
                            implicitHeight: contentHeight
                            model: cmbProgressZone.popup.visible ? cmbProgressZone.delegateModel : null
                            currentIndex: cmbProgressZone.highlightedIndex

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
                        id: dlgProgress
                        width: cmbProgressZone.width
                        contentItem: Text {
                            text: modelData
                            font.family: "Montserrat"
                            font.pixelSize: 13
                            color: dlgProgress.highlighted ? "#FFFFFF" : "#0F172A"
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            color: dlgProgress.highlighted ? "#3B82F6" : "transparent"
                            radius: 4
                        }
                        highlighted: cmbProgressZone.highlightedIndex === index
                    }

                    onCurrentTextChanged: {
                        if (bridgeObj && currentText) {
                            bridgeObj.selectedZone = currentText
                        }
                    }
                }
            }

            // Main Progress Card
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 520
                radius: 20
                color: "#FFFFFF"
                border.color: "#E2E8F0"
                border.width: 1
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    // Top Section (White)
                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 220

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 20
                            spacing: 6

                            // Row with Zone Name and Refresh Button
                            RowLayout {
                                Layout.fillWidth: true

                                Text {
                                    text: bridgeObj ? bridgeObj.selectedZone : "-"
                                    font.pixelSize: 38
                                    font.family: "Montserrat"
                                    font.bold: true
                                    color: "#1D4ED8"
                                }

                                Item { Layout.fillWidth: true }

                                Button {
                                    id: btnRefresh
                                    contentItem: Text {
                                        id: refreshText
                                        text: "🔄"
                                        font.pixelSize: 22
                                        color: btnRefresh.hovered ? "#3B82F6" : "#94A3B8"
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                        
                                        Behavior on color { ColorAnimation { duration: 150 } }
                                    }
                                    background: Rectangle { color: "transparent" }
                                    
                                    RotationAnimation {
                                        id: refreshSpin
                                        target: refreshText
                                        from: 0
                                        to: 360
                                        duration: 600
                                        direction: RotationAnimation.Clockwise
                                    }

                                    onClicked: {
                                        refreshSpin.start()
                                        if (bridgeObj) bridgeObj.update_stats()
                                    }
                                }
                            }

                            Text {
                                text: (bridgeObj ? bridgeObj.overallFraction : "0/0") + " assigned"
                                font.pixelSize: 13
                                font.family: "Montserrat"
                                color: "#64748B"
                            }

                            Item { Layout.fillHeight: true }

                            Text {
                                text: (bridgeObj ? bridgeObj.zoneCompletionPercentage : "0") + "%"
                                font.pixelSize: 48
                                font.family: "Montserrat"
                                font.bold: true
                                color: "#10B981"
                            }

                            Text {
                                text: "Complete"
                                font.pixelSize: 13
                                font.family: "Montserrat"
                                font.bold: true
                                color: "#64748B"
                            }
                        }
                    }

                    // Bottom Section (Premium Dark Blue Gradient)
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "#2563EB" }
                            GradientStop { position: 1.0; color: "#1D4ED8" }
                        }

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 20
                            spacing: 12

                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: "Today's Progress"
                                color: "white"
                                font.pixelSize: 12
                                font.family: "Montserrat"
                                font.bold: true
                                font.letterSpacing: 1.2
                            }

                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: bridgeObj ? bridgeObj.zoneReadFraction : "0/0"
                                color: "white"
                                font.pixelSize: 52
                                font.family: "Montserrat"
                                font.bold: true
                            }

                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: "Meters Read"
                                color: "#93C5FD"
                                font.pixelSize: 12
                                font.family: "Montserrat"
                            }

                            // Progress Bar
                            Rectangle {
                                Layout.fillWidth: true
                                height: 10
                                radius: 5
                                color: "#1E3A8A"

                                Rectangle {
                                    width: parent.width * (compPercent / 100.0)
                                    height: parent.height
                                    radius: 5
                                    color: "#10B981"

                                    Behavior on width {
                                        NumberAnimation { duration: 400; easing.type: Easing.OutQuad }
                                    }
                                }
                            }

                            // Separator
                            Rectangle {
                                Layout.fillWidth: true
                                height: 1
                                color: Qt.rgba(1.0, 1.0, 1.0, 0.15)
                            }

                            // Stats Rows with Glassmorphism Card Style
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12

                                // Remaining Card
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 74
                                    radius: 12
                                    color: Qt.rgba(1.0, 1.0, 1.0, 0.08)
                                    border.color: Qt.rgba(1.0, 1.0, 1.0, 0.15)
                                    border.width: 1

                                    ColumnLayout {
                                        anchors.centerIn: parent
                                        spacing: 2
                                        Text {
                                            Layout.alignment: Qt.AlignHCenter
                                            text: bridgeObj ? bridgeObj.zoneRemainingCount : "0"
                                            color: "white"
                                            font.pixelSize: 24
                                            font.family: "Montserrat"
                                            font.bold: true
                                        }
                                        Text {
                                            Layout.alignment: Qt.AlignHCenter
                                            text: "Remaining"
                                            color: "#93C5FD"
                                            font.pixelSize: 11
                                            font.family: "Montserrat"
                                        }
                                    }
                                }

                                // Flagged Card
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 74
                                    radius: 12
                                    color: Qt.rgba(1.0, 1.0, 1.0, 0.08)
                                    border.color: Qt.rgba(1.0, 1.0, 1.0, 0.15)
                                    border.width: 1

                                    ColumnLayout {
                                        anchors.centerIn: parent
                                        spacing: 2
                                        Text {
                                            Layout.alignment: Qt.AlignHCenter
                                            text: bridgeObj ? bridgeObj.zoneFlaggedCount : "0"
                                            color: "#FBBF24"
                                            font.pixelSize: 24
                                            font.family: "Montserrat"
                                            font.bold: true
                                        }
                                        Text {
                                            Layout.alignment: Qt.AlignHCenter
                                            text: "Flagged"
                                            color: "#93C5FD"
                                            font.pixelSize: 11
                                            font.family: "Montserrat"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
