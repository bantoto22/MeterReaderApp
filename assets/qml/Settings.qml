import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "TouchMetrics.js" as TouchMetrics

Rectangle {
    id: settingsRoot
    color: "#F4F7FB"

    readonly property var bridgeObj: (typeof appBridge !== "undefined" && appBridge) ? appBridge : null
    readonly property bool compactScreen: width <= 420
    readonly property bool wideLayout: width >= 760
    readonly property bool compactActionRow: width < 520
    readonly property int cardPadding: compactScreen ? 16 : 24
    readonly property int cardInset: compactScreen ? 32 : 48
    readonly property int cardSpacing: compactScreen ? 12 : 18

    Dialog {
        id: powerDialog
        anchors.centerIn: parent
        width: Math.min(parent.width - 40, 420)
        height: Math.min(parent.height - 48, settingsRoot.compactScreen ? 300 : 280)
        modal: true
        padding: settingsRoot.compactScreen ? 14 : 18
        standardButtons: Dialog.Ok | Dialog.Cancel
        title: "Power Off Device"
        onAccepted: {
            if (bridgeObj) bridgeObj.powerOffDevice()
        }
        contentItem: Flickable {
            clip: true
            contentWidth: width
            contentHeight: powerDialogText.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.VerticalFlick

            Text {
                id: powerDialogText
                width: powerDialog.availableWidth
                wrapMode: Text.WordWrap
                color: "#111827"
                font.family: "Montserrat"
                font.pixelSize: 12
                text: "Power off the device safely?\n\nThe app will sync pending readings first, then send a proper shutdown command to the Raspberry Pi to help prevent Raspberry Pi OS corruption. Only remove external power after the screen and Pi have fully shut down."
            }
        }
        background: Rectangle { color: "white"; radius: 8; border.color: "#D8E1EC" }
    }

    component ActionButton: Button {
        id: control
        property color buttonColor: "#2563EB"
        property color hoverColor: "#1D4ED8"
        implicitHeight: settingsRoot.compactScreen ? TouchMetrics.compactButtonHeight : TouchMetrics.buttonHeight
        contentItem: Text {
            text: control.text
            color: "white"
            font.family: "Montserrat"
            font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.bodyText : TouchMetrics.buttonText
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
        Layout.fillWidth: true
        contentItem: Text {
            text: sw.labelText
            font.family: "Montserrat"
            font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.helperText : TouchMetrics.bodyText
            font.bold: true
            color: "#111827"
            verticalAlignment: Text.AlignVCenter
            leftPadding: sw.indicator.width + 10
            wrapMode: Text.WordWrap
        }
        indicator: Rectangle {
            implicitWidth: 52
            implicitHeight: 30
            radius: 11
            color: sw.checked ? "#2563EB" : "#D8E1EC"
            Rectangle {
                x: sw.checked ? parent.width - width - 3 : 3
                y: 3
                width: 24
                height: 24
                radius: 12
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
        padding: settingsRoot.compactScreen ? 14 : 18
        standardButtons: Dialog.Close
        contentItem: ScrollView {
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            TextArea {
                width: logsDialog.availableWidth
                text: bridgeObj ? bridgeObj.syncLogs : "No sync activity yet."
                readOnly: true
                wrapMode: TextEdit.Wrap
                color: "#111827"
                font.family: "Montserrat"
                font.pixelSize: TouchMetrics.bodyText
                background: Rectangle { color: "#F8FAFD"; radius: 6 }
            }
        }
        background: Rectangle { color: "white"; radius: 8; border.color: "#D8E1EC" }
    }

    Dialog {
        id: supabaseLogsDialog
        title: "Supabase Activity"
        anchors.centerIn: parent
        width: Math.min(parent.width - 32, 560)
        height: Math.min(parent.height - 60, 520)
        modal: true
        padding: settingsRoot.compactScreen ? 14 : 18
        standardButtons: Dialog.Close
        contentItem: ScrollView {
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            TextArea {
                width: supabaseLogsDialog.availableWidth
                text: bridgeObj ? bridgeObj.supabaseLogs : "No Supabase activity yet."
                readOnly: true
                wrapMode: TextEdit.Wrap
                color: "#111827"
                font.family: "Montserrat"
                font.pixelSize: TouchMetrics.bodyText
                background: Rectangle { color: "#F8FAFD"; radius: 6 }
            }
        }
        background: Rectangle { color: "white"; radius: 8; border.color: "#D8E1EC" }
    }

    ScrollablePage {
        anchors.fill: parent
        maxContentWidth: 460
        pageSidePadding: settingsRoot.compactScreen ? TouchMetrics.compactPageMargin : TouchMetrics.pageMargin
        pageTopPadding: settingsRoot.compactScreen ? TouchMetrics.compactPageMargin : TouchMetrics.pageMargin
        pageBottomPadding: settingsRoot.compactScreen ? 20 : 36

        ColumnLayout {
            Layout.fillWidth: true
            spacing: settingsRoot.compactScreen ? TouchMetrics.compactSectionSpacing : TouchMetrics.sectionSpacing

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: syncCardContent.implicitHeight + settingsRoot.cardInset
                radius: 8
                color: "white"
                border.color: "#D8E1EC"

                ColumnLayout {
                    id: syncCardContent
                    anchors.fill: parent
                    anchors.margins: settingsRoot.cardPadding
                    spacing: settingsRoot.cardSpacing

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: settingsRoot.compactScreen ? 12 : 16
                        Rectangle {
                            Layout.preferredWidth: settingsRoot.compactScreen ? 48 : 56
                            Layout.preferredHeight: settingsRoot.compactScreen ? 48 : 56
                            radius: 8
                            color: "#2563EB"
                            Text { anchors.centerIn: parent; text: "SYNC"; color: "white"; font.family: "Montserrat"; font.pixelSize: 9; font.bold: true }
                        }
                        ColumnLayout {
                            spacing: settingsRoot.compactScreen ? 4 : 6
                            Text { text: "Sync Diagnostics"; color: "#111827"; font.family: "Montserrat"; font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.bodyText + 2 : TouchMetrics.sectionTitle; font.bold: true }
                            Text { text: "Sync: " + (bridgeObj ? bridgeObj.syncStatus : "Offline"); color: bridgeObj ? bridgeObj.syncStatusColor : "#526176"; font.family: "Montserrat"; font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.helperText + 1 : TouchMetrics.bodyText; font.bold: true }
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: settingsRoot.wideLayout ? 3 : 1
                        columnSpacing: settingsRoot.compactScreen ? 20 : 34
                        rowSpacing: settingsRoot.compactScreen ? 12 : 18

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: settingsRoot.compactScreen ? 6 : 9
                            Text { text: "Pending: " + (bridgeObj ? bridgeObj.syncPendingCount : 0); color: "#526176"; font.family: "Montserrat"; font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.helperText + 1 : TouchMetrics.bodyText }
                            Text { text: "Supabase: " + (bridgeObj ? bridgeObj.supabaseStatus : "Offline"); color: bridgeObj && bridgeObj.supabaseStatus === "Online" ? "#0F766E" : "#B45309"; font.family: "Montserrat"; font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.helperText + 1 : TouchMetrics.bodyText; font.bold: true; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            Text { text: "Supabase pending: " + (bridgeObj ? bridgeObj.supabasePendingCount : 0); color: "#526176"; font.family: "Montserrat"; font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.helperText + 1 : TouchMetrics.bodyText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            Text { text: "Supabase last sync: " + (bridgeObj ? bridgeObj.supabaseLastSync : "Never"); color: "#526176"; font.family: "Montserrat"; font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.helperText + 1 : TouchMetrics.bodyText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            Text { text: "Save Target: " + (bridgeObj ? bridgeObj.saveTarget : "Local SQLite only"); color: "#526176"; font.family: "Montserrat"; font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.helperText + 1 : TouchMetrics.bodyText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            Text { text: "Backup: " + (bridgeObj ? bridgeObj.backupState : "Not configured"); color: "#526176"; font.family: "Montserrat"; font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.helperText + 1 : TouchMetrics.bodyText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            Text { text: "Last Sync: " + (bridgeObj ? bridgeObj.lastSync : "Never"); color: "#526176"; font.family: "Montserrat"; font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.helperText + 1 : TouchMetrics.bodyText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            Text {
                                text: "Last pull: "
                                      + (bridgeObj ? bridgeObj.lastPullCount : 0)
                                      + " pulled | "
                                      + (bridgeObj ? bridgeObj.lastPullMirror : 0)
                                      + " mirrored"
                                color: "#526176"
                                font.family: "Montserrat"
                                font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.helperText + 1 : TouchMetrics.bodyText
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                        }

                        Rectangle {
                            visible: settingsRoot.wideLayout
                            Layout.preferredWidth: 1
                            Layout.fillHeight: true
                            color: "#D8E1EC"
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: settingsRoot.compactScreen ? 10 : 12
                            Rectangle {
                                Layout.fillWidth: true
                                radius: 10
                                color: "#F8FAFD"
                                border.color: "#D8E1EC"
                                implicitHeight: manualSyncColumn.implicitHeight + 24
                                ColumnLayout {
                                    id: manualSyncColumn
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 6
                                    Text {
                                        text: "Manual Sync Only"
                                        color: "#111827"
                                        font.family: "Montserrat"
                                        font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.bodyText : TouchMetrics.subheading
                                        font.bold: true
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        wrapMode: Text.WordWrap
                                        text: "Readings are saved locally on the device and uploaded only when Manual Sync is tapped. Schedule downloads happen on login and manual refresh."
                                        color: "#526176"
                                        font.family: "Montserrat"
                                        font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.helperText + 1 : TouchMetrics.bodyText
                                    }
                                }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: "#D8E1EC" }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: settingsRoot.compactActionRow ? 2 : 3
                        columnSpacing: settingsRoot.compactScreen ? 10 : 12
                        rowSpacing: settingsRoot.compactScreen ? 10 : 12
                        ActionButton {
                            text: "Manual Sync"
                            Layout.fillWidth: true
                            onClicked: { if (bridgeObj) bridgeObj.syncNow() }
                        }
                        ActionButton {
                            text: "View Logs"
                            buttonColor: "#111827"
                            hoverColor: "#1F2937"
                            Layout.fillWidth: true
                            onClicked: logsDialog.open()
                        }
                        ActionButton {
                            text: "Supabase Logs"
                            buttonColor: "#0F766E"
                            hoverColor: "#115E59"
                            Layout.fillWidth: true
                            onClicked: supabaseLogsDialog.open()
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: printerCardContent.implicitHeight + 48
                radius: 8
                color: "white"
                border.color: "#D8E1EC"

                ColumnLayout {
                    id: printerCardContent
                    anchors.fill: parent
                    anchors.margins: settingsRoot.cardPadding
                    spacing: settingsRoot.cardSpacing

                    Text {
                        text: "Printer Settings"
                        color: "#111827"
                        font.family: "Montserrat"
                        font.pixelSize: TouchMetrics.sectionTitle
                        font.bold: true
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Send a direct ESC/POS test receipt to the USB thermal printer connected at /dev/usb/lp0."
                        color: "#526176"
                        font.family: "Montserrat"
                        font.pixelSize: TouchMetrics.bodyText
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        text: "Printer Status: " + (bridgeObj && bridgeObj.testPrintBusy ? "Printing..." : "Ready")
                        color: bridgeObj && bridgeObj.testPrintBusy ? "#B45309" : "#0F766E"
                        font.family: "Montserrat"
                        font.pixelSize: TouchMetrics.bodyText
                        font.bold: true
                    }

                    ActionButton {
                        text: bridgeObj && bridgeObj.testPrintBusy ? "Printing..." : "Test Print"
                        buttonColor: "#0F766E"
                        hoverColor: "#115E59"
                        Layout.fillWidth: true
                        enabled: bridgeObj ? !bridgeObj.testPrintBusy : false
                        onClicked: { if (bridgeObj) bridgeObj.printTestReceipt() }
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
                    anchors.margins: settingsRoot.cardPadding
                    spacing: settingsRoot.cardSpacing

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
                            spacing: settingsRoot.compactScreen ? 4 : 6
                            Text { text: "Connectivity"; color: "#111827"; font.family: "Montserrat"; font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.bodyText + 2 : TouchMetrics.sectionTitle; font.bold: true }
                            Text {
                                text: bridgeObj ? bridgeObj.wifiStatus : "Status: Checking..."
                                color: bridgeObj ? bridgeObj.wifiStatusColor : "#526176"
                                font.family: "Montserrat"
                                font.pixelSize: settingsRoot.compactScreen ? TouchMetrics.helperText + 1 : TouchMetrics.bodyText
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
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
                            font.pixelSize: TouchMetrics.bodyText
                            wrapMode: Text.WordWrap
                        }
                    }

                    Text {
                        text: "Network"
                        color: "#111827"
                        font.family: "Montserrat"
                        font.pixelSize: TouchMetrics.bodyText
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
                            font.pixelSize: TouchMetrics.bodyText
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
                                implicitHeight: TouchMetrics.inputHeight
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
                                implicitHeight: TouchMetrics.inputHeight
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
                        font.pixelSize: TouchMetrics.bodyText
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 16
                        TextField {
                            id: txtWifiPassword
                            property string keyboardMode: "password"
                            Layout.fillWidth: true
                            placeholderText: "Password"
                            echoMode: TextInput.Password
                            inputMethodHints: Qt.ImhHiddenText | Qt.ImhNoPredictiveText | Qt.ImhSensitiveData
                            color: "#111827"
                            font.family: "Montserrat"
                            font.pixelSize: TouchMetrics.bodyText
                            background: Rectangle { implicitHeight: TouchMetrics.inputHeight; radius: 7; color: "#F8FAFD"; border.color: txtWifiPassword.activeFocus ? "#60A5FA" : "#C9D5E3" }
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
                    anchors.margins: settingsRoot.cardPadding
                    spacing: settingsRoot.cardSpacing

                    Text {
                        text: "Power"
                        color: "#111827"
                        font.family: "Montserrat"
                        font.pixelSize: TouchMetrics.sectionTitle
                        font.bold: true
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Use this before switching off external power to help prevent Raspberry Pi OS corruption."
                        color: "#526176"
                        font.family: "Montserrat"
                        font.pixelSize: TouchMetrics.bodyText
                        wrapMode: Text.WordWrap
                    }

                    ActionButton {
                        text: "Power Off Device"
                        buttonColor: "#B91C1C"
                        hoverColor: "#991B1B"
                        Layout.fillWidth: settingsRoot.compactScreen
                        Layout.preferredWidth: settingsRoot.compactScreen ? -1 : 168
                        onClicked: powerDialog.open()
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
