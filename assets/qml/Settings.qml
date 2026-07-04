import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: settingsRoot
    color: "#F4F7FB"

    readonly property var bridgeObj: (typeof appBridge !== "undefined" && appBridge) ? appBridge : null
    readonly property bool wideLayout: width >= 760

    Dialog {
        id: powerDialog
        anchors.centerIn: parent
        width: Math.min(parent.width - 40, 420)
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        title: "Power Off Device"
        onAccepted: {
            if (bridgeObj) bridgeObj.powerOffDevice()
        }
        contentItem: Text {
            width: parent.width
            wrapMode: Text.WordWrap
            color: "#111827"
            font.family: "Montserrat"
            font.pixelSize: 12
            text: "Power off the device safely?\n\nThe app will sync pending readings first, then send a proper shutdown command to the Raspberry Pi to help prevent Raspberry Pi OS corruption. Only remove external power after the screen and Pi have fully shut down."
        }
        background: Rectangle { color: "white"; radius: 8; border.color: "#D8E1EC" }
    }

    component ActionButton: Button {
        id: control
        property color buttonColor: "#2563EB"
        property color hoverColor: "#1D4ED8"
        implicitHeight: 46
        contentItem: Text {
            text: control.text
            color: "white"
            font.family: "Montserrat"
            font.pixelSize: 11
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 7
            color: control.enabled ? (control.hovered ? control.hoverColor : control.buttonColor) : "#94A3B8"
        }
    }

    component CustomSwitch: Switch {
        id: sw
        property string labelText: ""
        contentItem: Text {
            text: sw.labelText
            font.family: "Montserrat"
            font.pixelSize: 11
            font.bold: true
            color: "#111827"
            verticalAlignment: Text.AlignVCenter
            leftPadding: sw.indicator.width + 10
        }
        indicator: Rectangle {
            implicitWidth: 42
            implicitHeight: 22
            radius: 11
            color: sw.checked ? "#2563EB" : "#D8E1EC"
            Rectangle {
                x: sw.checked ? parent.width - width - 3 : 3
                y: 3
                width: 16
                height: 16
                radius: 8
                color: "white"
                Behavior on x { NumberAnimation { duration: 140 } }
            }
        }
    }

    Dialog {
        id: logsDialog
        title: "Recent Sync Activity"
        anchors.centerIn: parent
        width: Math.min(parent.width - 32, 560)
        height: Math.min(parent.height - 60, 520)
        modal: true
        standardButtons: Dialog.Close
        contentItem: ScrollView {
            TextArea {
                text: bridgeObj ? bridgeObj.syncLogs : "No sync activity yet."
                readOnly: true
                wrapMode: TextEdit.Wrap
                color: "#111827"
                font.family: "Montserrat"
                font.pixelSize: 11
                background: Rectangle { color: "#F8FAFD"; radius: 6 }
            }
        }
        background: Rectangle { color: "white"; radius: 8; border.color: "#D8E1EC" }
    }

    ScrollView {
        anchors.fill: parent
        contentWidth: parent.width

        ColumnLayout {
            width: Math.min(parent.width - 40, 1160)
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: 20
            spacing: 14

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: syncCardContent.implicitHeight + 48
                radius: 8
                color: "white"
                border.color: "#D8E1EC"

                ColumnLayout {
                    id: syncCardContent
                    anchors.fill: parent
                    anchors.margins: 24
                    spacing: 18

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 16
                        Rectangle {
                            Layout.preferredWidth: 56
                            Layout.preferredHeight: 56
                            radius: 8
                            color: "#2563EB"
                            Text { anchors.centerIn: parent; text: "SYNC"; color: "white"; font.family: "Montserrat"; font.pixelSize: 9; font.bold: true }
                        }
                        ColumnLayout {
                            spacing: 6
                            Text { text: "Sync Diagnostics"; color: "#111827"; font.family: "Montserrat"; font.pixelSize: 16; font.bold: true }
                            Text { text: "Sync: " + (bridgeObj ? bridgeObj.syncStatus : "Offline"); color: bridgeObj ? bridgeObj.syncStatusColor : "#526176"; font.family: "Montserrat"; font.pixelSize: 11; font.bold: true }
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: settingsRoot.wideLayout ? 3 : 1
                        columnSpacing: 34
                        rowSpacing: 18

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 9
                            Text { text: "Pending: " + (bridgeObj ? bridgeObj.syncPendingCount : 0); color: "#526176"; font.family: "Montserrat"; font.pixelSize: 11 }
                            Text { text: "Save Target: " + (bridgeObj ? bridgeObj.saveTarget : "Local SQLite only"); color: "#526176"; font.family: "Montserrat"; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            Text { text: "Backup: " + (bridgeObj ? bridgeObj.backupState : "Not configured"); color: "#526176"; font.family: "Montserrat"; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            Text { text: "Last Sync: " + (bridgeObj ? bridgeObj.lastSync : "Never"); color: "#526176"; font.family: "Montserrat"; font.pixelSize: 11; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            Text { text: "Last pull mirrored: " + (bridgeObj ? bridgeObj.lastPullMirror : 0) + " records"; color: "#526176"; font.family: "Montserrat"; font.pixelSize: 11 }
                        }

                        Rectangle {
                            visible: settingsRoot.wideLayout
                            Layout.preferredWidth: 1
                            Layout.fillHeight: true
                            color: "#D8E1EC"
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            CustomSwitch {
                                labelText: "Auto Pull from Main DB (online)"
                                checked: bridgeObj ? bridgeObj.autoPullEnabled : true
                                onToggled: { if (bridgeObj) bridgeObj.autoPullEnabled = checked }
                            }
                            CustomSwitch {
                                labelText: "Auto Push New Readings"
                                checked: bridgeObj ? bridgeObj.autoPushEnabled : true
                                onToggled: { if (bridgeObj) bridgeObj.autoPushEnabled = checked }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Text { text: "Pull interval (sec):"; color: "#526176"; font.family: "Montserrat"; font.pixelSize: 11 }
                                TextField {
                                    id: txtInterval
                                    Layout.preferredWidth: 88
                                    text: bridgeObj ? bridgeObj.pullInterval : 60
                                    validator: IntValidator { bottom: 15 }
                                    horizontalAlignment: Text.AlignHCenter
                                    color: "#111827"
                                    font.family: "Montserrat"
                                    font.pixelSize: 11
                                    background: Rectangle { radius: 7; color: "#F8FAFD"; border.color: txtInterval.activeFocus ? "#60A5FA" : "#C9D5E3" }
                                    onEditingFinished: { if (bridgeObj && text.length) bridgeObj.pullInterval = parseInt(text) }
                                }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: "#D8E1EC" }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        ActionButton { text: "Sync Now"; Layout.preferredWidth: 138; onClicked: { if (bridgeObj) bridgeObj.syncNow() } }
                        ActionButton { text: "View Logs"; buttonColor: "#111827"; hoverColor: "#1F2937"; Layout.preferredWidth: 138; onClicked: logsDialog.open() }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: wifiCardContent.implicitHeight + 48
                radius: 8
                color: "white"
                border.color: "#D8E1EC"

                ColumnLayout {
                    id: wifiCardContent
                    anchors.fill: parent
                    anchors.margins: 24
                    spacing: 14

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 16
                        Rectangle {
                            Layout.preferredWidth: 56
                            Layout.preferredHeight: 56
                            radius: 8
                            color: "#2563EB"
                            Text { anchors.centerIn: parent; text: "WI-FI"; color: "white"; font.family: "Montserrat"; font.pixelSize: 9; font.bold: true }
                        }
                        ColumnLayout {
                            spacing: 6
                            Text { text: "Connectivity"; color: "#111827"; font.family: "Montserrat"; font.pixelSize: 16; font.bold: true }
                            Text { text: bridgeObj ? bridgeObj.wifiStatus : "Status: Checking..."; color: bridgeObj ? bridgeObj.wifiStatusColor : "#526176"; font.family: "Montserrat"; font.pixelSize: 11; elide: Text.ElideRight; Layout.maximumWidth: settingsRoot.width - 140 }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 7
                        color: "#F8FAFD"
                        border.color: "#D8E1EC"
                        implicitHeight: wifiHintText.implicitHeight + 24

                        Text {
                            id: wifiHintText
                            anchors.fill: parent
                            anchors.margins: 12
                            text: {
                                var networks = bridgeObj ? bridgeObj.wifiNetworks : []
                                var current = cmbWifi.editText.length ? cmbWifi.editText : cmbWifi.currentText
                                if (current.length > 0)
                                    return "Selected network: " + current
                                if (networks && networks.length > 0)
                                    return networks.length + " network(s) available nearby."
                                return "Scan for nearby Wi-Fi networks, then choose one to connect."
                            }
                            color: "#526176"
                            font.family: "Montserrat"
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }
                    }

                    Text {
                        text: "Network"
                        color: "#111827"
                        font.family: "Montserrat"
                        font.pixelSize: 11
                        font.bold: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 16
                        ComboBox {
                            id: cmbWifi
                            Layout.fillWidth: true
                            editable: false
                            model: bridgeObj ? bridgeObj.wifiNetworks : []
                            font.family: "Montserrat"
                            font.pixelSize: 11
                            leftPadding: 14
                            rightPadding: 42

                            contentItem: TextInput {
                                leftPadding: 0
                                rightPadding: 0
                                text: cmbWifi.editable ? cmbWifi.editText : cmbWifi.displayText
                                color: "#111827"
                                selectionColor: "#BFDBFE"
                                selectedTextColor: "#111827"
                                font: cmbWifi.font
                                verticalAlignment: TextInput.AlignVCenter
                                selectByMouse: true
                                clip: true
                            }

                            indicator: Canvas {
                                x: cmbWifi.width - width - 15
                                y: (cmbWifi.height - height) / 2
                                width: 12
                                height: 8
                                contextType: "2d"
                                onPaint: {
                                    context.reset()
                                    context.moveTo(1, 1)
                                    context.lineTo(width / 2, height - 1)
                                    context.lineTo(width - 1, 1)
                                    context.strokeStyle = "#526176"
                                    context.lineWidth = 2
                                    context.stroke()
                                }
                            }

                            delegate: ItemDelegate {
                                width: cmbWifi.width
                                implicitHeight: 42
                                highlighted: cmbWifi.highlightedIndex === index
                                contentItem: Text {
                                    text: modelData
                                    color: "#111827"
                                    font: cmbWifi.font
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                                background: Rectangle {
                                    color: parent.highlighted ? "#DBEAFE" : "#FFFFFF"
                                }
                            }

                            popup.background: Rectangle {
                                color: "#FFFFFF"
                                border.color: "#C9D5E3"
                                radius: 7
                            }

                            background: Rectangle {
                                implicitHeight: 48
                                radius: 7
                                color: "#F8FAFD"
                                border.color: cmbWifi.activeFocus ? "#60A5FA" : "#C9D5E3"
                            }
                        }
                        ActionButton {
                            text: bridgeObj && bridgeObj.wifiBusy ? "Working..." : "Scan"
                            Layout.preferredWidth: 96
                            enabled: bridgeObj ? !bridgeObj.wifiBusy : false
                            onClicked: { if (bridgeObj) bridgeObj.scanWifiNetworks() }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Choose a network from the scan results, then enter its password below."
                        color: "#526176"
                        font.family: "Montserrat"
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 16
                        TextField {
                            id: txtWifiPassword
                            Layout.fillWidth: true
                            placeholderText: "Password"
                            echoMode: TextInput.Password
                            color: "#111827"
                            font.family: "Montserrat"
                            font.pixelSize: 11
                            background: Rectangle { implicitHeight: 48; radius: 7; color: "#F8FAFD"; border.color: txtWifiPassword.activeFocus ? "#60A5FA" : "#C9D5E3" }
                            onAccepted: btnConnect.clicked()
                        }
                        ActionButton {
                            id: btnConnect
                            text: bridgeObj && bridgeObj.wifiBusy ? "Working..." : "Connect"
                            buttonColor: "#10B981"
                            hoverColor: "#059669"
                            Layout.preferredWidth: 96
                            enabled: bridgeObj ? !bridgeObj.wifiBusy : false
                            onClicked: {
                                if (bridgeObj) {
                                    var ssid = cmbWifi.editText.length ? cmbWifi.editText : cmbWifi.currentText
                                    bridgeObj.connectWifiNetwork(ssid, txtWifiPassword.text)
                                    txtWifiPassword.text = ""
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: powerCardContent.implicitHeight + 48
                radius: 8
                color: "white"
                border.color: "#D8E1EC"

                ColumnLayout {
                    id: powerCardContent
                    anchors.fill: parent
                    anchors.margins: 24
                    spacing: 14

                    Text {
                        text: "Power"
                        color: "#111827"
                        font.family: "Montserrat"
                        font.pixelSize: 16
                        font.bold: true
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Use this before switching off external power to help prevent Raspberry Pi OS corruption."
                        color: "#526176"
                        font.family: "Montserrat"
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                    }

                    ActionButton {
                        text: "Power Off Device"
                        buttonColor: "#B91C1C"
                        hoverColor: "#991B1B"
                        Layout.preferredWidth: 168
                        onClicked: powerDialog.open()
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
