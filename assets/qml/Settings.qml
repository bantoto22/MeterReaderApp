import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: settingsRoot
    color: "#F8FAFC"

    // Safe bridge reference
    readonly property var bridgeObj: (typeof appBridge !== "undefined" && appBridge) ? appBridge : null

    // Helper component for modern sliding toggle switch
    component CustomSwitch : Switch {
        id: sw
        property string labelText: ""
        
        contentItem: Text {
            text: sw.labelText
            font.family: "Montserrat"
            font.pixelSize: 13
            font.bold: true
            color: "#334155"
            verticalAlignment: Text.AlignVCenter
            leftPadding: sw.indicator.width + 10
        }
        
        indicator: Rectangle {
            implicitWidth: 46
            implicitHeight: 24
            radius: 12
            color: sw.checked ? "#10B981" : "#E2E8F0"
            border.color: sw.checked ? "#059669" : "#CBD5E1"
            border.width: 1
            Behavior on color { ColorAnimation { duration: 150 } }

            Rectangle {
                x: sw.checked ? parent.width - width - 3 : 3
                y: 3
                width: 18
                height: 18
                radius: 9
                color: "white"
                
                Behavior on x {
                    NumberAnimation { duration: 150; easing.type: Easing.OutQuad }
                }
            }
        }
    }

    ScrollView {
        anchors.fill: parent
        contentWidth: parent.width

        ColumnLayout {
            width: parent.width - 32
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: 16
            spacing: 16

            // Settings Header
            Text {
                text: "Settings"
                font.pixelSize: 18
                font.family: "Montserrat"
                font.bold: true
                color: "#0F172A"
            }

            // Connection Status & Info Card
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 180
                radius: 16
                color: "#FFFFFF"
                border.color: "#E2E8F0"
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 10

                    Text {
                        text: "Sync Connection"
                        font.pixelSize: 13
                        font.family: "Montserrat"
                        font.bold: true
                        color: "#0F172A"
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Status"; font.pixelSize: 12; font.family: "Montserrat"; color: "#64748B" }
                        Item { Layout.fillWidth: true }
                        
                        // Badge-like status display
                        Rectangle {
                            Layout.preferredWidth: 80
                            Layout.preferredHeight: 24
                            radius: 12
                            color: {
                                var baseCol = bridgeObj ? bridgeObj.syncStatusColor : "#64748B"
                                return baseCol + "1C"
                            }
                            border.color: bridgeObj ? bridgeObj.syncStatusColor : "#64748B"
                            border.width: 1
                            
                            Text {
                                anchors.centerIn: parent
                                text: bridgeObj ? bridgeObj.syncStatus : "Offline"
                                font.pixelSize: 10
                                font.family: "Montserrat"
                                font.bold: true
                                color: bridgeObj ? bridgeObj.syncStatusColor : "#64748B"
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Pending Records"; font.pixelSize: 12; font.family: "Montserrat"; color: "#64748B" }
                        Item { Layout.fillWidth: true }
                        Text { text: bridgeObj ? bridgeObj.syncPendingCount : "0"; font.pixelSize: 12; font.family: "Montserrat"; font.bold: true; color: "#0F172A" }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Save Target"; font.pixelSize: 12; font.family: "Montserrat"; color: "#64748B" }
                        Item { Layout.fillWidth: true }
                        Text { text: bridgeObj ? bridgeObj.saveTarget : "Local SQLite only"; font.pixelSize: 12; font.family: "Montserrat"; font.bold: true; color: "#0F172A" }
                    }
                }
            }

            // Sync Diagnostics Card
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 280
                radius: 16
                color: "#FFFFFF"
                border.color: "#E2E8F0"
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 12

                    Text {
                        text: "Sync Diagnostics"
                        font.pixelSize: 13
                        font.family: "Montserrat"
                        font.bold: true
                        color: "#0F172A"
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Cloud Backup"; font.pixelSize: 12; font.family: "Montserrat"; color: "#64748B" }
                        Item { Layout.fillWidth: true }
                        Text { text: bridgeObj ? bridgeObj.backupState : "Not configured"; font.pixelSize: 12; font.family: "Montserrat"; font.bold: true; color: "#0F172A" }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Last Synced At"; font.pixelSize: 12; font.family: "Montserrat"; color: "#64748B" }
                        Item { Layout.fillWidth: true }
                        Text { text: bridgeObj ? bridgeObj.lastSync : "Never"; font.pixelSize: 12; font.family: "Montserrat"; font.bold: true; color: "#0F172A" }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Last Mirrored Count"; font.pixelSize: 12; font.family: "Montserrat"; color: "#64748B" }
                        Item { Layout.fillWidth: true }
                        Text { text: (bridgeObj ? bridgeObj.lastPullMirror : 0) + " records"; font.pixelSize: 12; font.family: "Montserrat"; font.bold: true; color: "#0F172A" }
                    }

                    // Separator
                    Rectangle {
                        Layout.fillWidth: true
                        height: 1
                        color: "#F1F5F9"
                    }

                    // Auto sync settings using custom toggle switches
                    CustomSwitch {
                        id: swAutoPull
                        labelText: "Auto Pull from Main DB"
                        checked: bridgeObj ? bridgeObj.autoPullEnabled : true
                        onCheckedChanged: { if (bridgeObj) bridgeObj.autoPullEnabled = checked }
                    }

                    CustomSwitch {
                        id: swAutoPush
                        labelText: "Auto Push New Readings"
                        checked: bridgeObj ? bridgeObj.autoPushEnabled : true
                        onCheckedChanged: { if (bridgeObj) bridgeObj.autoPushEnabled = checked }
                    }

                    // Pull Interval Input
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Text {
                            text: "Pull Interval (seconds):"
                            font.pixelSize: 12
                            font.family: "Montserrat"
                            color: "#64748B"
                        }

                        Item { Layout.fillWidth: true }

                        TextField {
                            id: txtInterval
                            text: bridgeObj ? bridgeObj.pullInterval : 60
                            font.pixelSize: 12
                            font.family: "Montserrat"
                            font.bold: true
                            color: "#0F172A"
                            placeholderTextColor: "#94A3B8"
                            horizontalAlignment: Text.AlignHCenter
                            Layout.preferredWidth: 64
                            validator: IntValidator { bottom: 15 }
                            background: Rectangle {
                                radius: 8
                                border.color: txtInterval.activeFocus ? "#3B82F6" : "#E2E8F0"
                                border.width: txtInterval.activeFocus ? 2 : 1
                                color: txtInterval.activeFocus ? "#FFFFFF" : "#F8FAFC"
                                Behavior on border.color { ColorAnimation { duration: 150 } }
                            }
                            onTextChanged: {
                                if (bridgeObj) {
                                    var val = parseInt(text)
                                    if (!isNaN(val)) {
                                        bridgeObj.pullInterval = val
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
