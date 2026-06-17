import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: progressRoot
    color: "#F8FAFC"

    readonly property var bridgeObj: (typeof appBridge !== "undefined" && appBridge) ? appBridge : null
    readonly property real compPercent: bridgeObj ? bridgeObj.zoneCompletionPercentage : 0.0
    property int pendingReprintConsumerId: -1

    Dialog {
        id: reprintConfirmDialog
        title: "Print Details"
        modal: true
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 320)
        standardButtons: Dialog.Yes | Dialog.No

        contentItem: Text {
            text: "Print this consumer's saved details?"
            wrapMode: Text.WordWrap
            color: "#0F172A"
            font.family: "Montserrat"
            font.pixelSize: 12
        }

        background: Rectangle {
            color: "white"
            radius: 14
            border.color: "#CBD5E1"
            border.width: 1
        }

        onAccepted: {
            if (bridgeObj && pendingReprintConsumerId >= 0) {
                bridgeObj.reprintZoneConsumer(pendingReprintConsumerId)
            }
            pendingReprintConsumerId = -1
        }
        onRejected: pendingReprintConsumerId = -1
    }

    StackLayout {
        anchors.fill: parent
        currentIndex: bridgeObj && bridgeObj.progressDetailsVisible ? 1 : 0

        Item {
            ScrollView {
                anchors.fill: parent
                contentWidth: parent.width

                ColumnLayout {
                    width: parent.width - 32
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: parent.top
                    anchors.topMargin: 16
                    spacing: 16

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

                            delegate: ItemDelegate {
                                width: cmbProgressZone.width
                                text: modelData
                                highlighted: cmbProgressZone.highlightedIndex === index
                            }

                            onCurrentTextChanged: {
                                if (bridgeObj && currentText) {
                                    bridgeObj.selectedZone = currentText
                                }
                            }
                        }
                    }

                    Rectangle {
                        id: zoneProgressCard
                        Layout.fillWidth: true
                        implicitHeight: 520
                        radius: 20
                        color: "#FFFFFF"
                        border.color: "#E2E8F0"
                        border.width: 1
                        clip: true
                        scale: progressCardMouse.pressed ? 0.985 : 1.0
                        transformOrigin: Item.Center
                        Behavior on scale { NumberAnimation { duration: 90 } }

                        MouseArea {
                            id: progressCardMouse
                            anchors.fill: parent
                            onClicked: {
                                if (bridgeObj) bridgeObj.openProgressDetails()
                            }
                        }

                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 0

                            Item {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 220

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 20
                                    spacing: 6

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

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Layout.margins: 12
                                radius: 18
                                clip: true
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
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        height: 1
                                        color: Qt.rgba(1.0, 1.0, 1.0, 0.15)
                                    }

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 12

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

        Item {
            ScrollView {
                anchors.fill: parent
                contentWidth: parent.width

                ColumnLayout {
                    width: parent.width - 30
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: parent.top
                    anchors.topMargin: 12
                    spacing: 12

                    Rectangle {
                        Layout.fillWidth: true
                        height: 50
                        radius: 12
                        clip: true
                        color: "#1D4ED8"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 12

                            Button {
                                id: btnBackDetails
                                implicitWidth: 42
                                implicitHeight: 42
                                scale: pressed ? 0.92 : 1.0
                                Behavior on scale { NumberAnimation { duration: 80 } }
                                text: "<"
                                background: Rectangle { color: "transparent" }
                                contentItem: Text {
                                    text: "<"
                                    color: "white"
                                    font.pixelSize: 18
                                    font.bold: true
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                                onClicked: { if (bridgeObj) bridgeObj.closeProgressDetails() }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: bridgeObj ? (bridgeObj.selectedZone + " - Details") : "Details"
                                color: "white"
                                font.family: "Montserrat"
                                font.pixelSize: 14
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 12
                        color: "white"
                        border.color: "#E2E8F0"
                        border.width: 1
                        implicitHeight: 44

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            text: {
                                var rows = bridgeObj ? bridgeObj.zoneConsumers : []
                                var readCount = rows.filter(function(row) { return row.is_read; }).length
                                return "Total: " + rows.length + " | Read: " + readCount + " | Remaining: " + (rows.length - readCount)
                            }
                            font.family: "Montserrat"
                            font.pixelSize: 11
                            font.bold: true
                            color: "#0F172A"
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 14
                        color: "white"
                        border.color: "#CBD5E1"
                        border.width: 1
                        implicitHeight: 480

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 6

                            GridLayout {
                                Layout.fillWidth: true
                                columns: 5
                                columnSpacing: 8
                                rowSpacing: 0

                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 34; color: "#E2E8F0"; Text { anchors.centerIn: parent; text: "Meter"; font.bold: true; color: "#64748B"; font.pixelSize: 9 } }
                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 34; color: "#E2E8F0"; Text { anchors.centerIn: parent; text: "Name"; font.bold: true; color: "#64748B"; font.pixelSize: 9 } }
                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 34; color: "#E2E8F0"; Text { anchors.centerIn: parent; text: "Status"; font.bold: true; color: "#64748B"; font.pixelSize: 9 } }
                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 34; color: "#E2E8F0"; Text { anchors.centerIn: parent; text: "Reading"; font.bold: true; color: "#64748B"; font.pixelSize: 9 } }
                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 34; color: "#E2E8F0"; Text { anchors.centerIn: parent; text: "Action"; font.bold: true; color: "#64748B"; font.pixelSize: 9 } }
                            }

                            ListView {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                model: bridgeObj ? bridgeObj.zoneConsumers : []
                                spacing: 1

                                delegate: Rectangle {
                                    width: ListView.view.width
                                    height: 40
                                    color: modelData.is_read ? "#E8F5E9" : "white"

                                    GridLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 6
                                        anchors.rightMargin: 6
                                        columns: 5
                                        columnSpacing: 8

                                        Text { Layout.fillWidth: true; text: modelData.meter_no; font.pixelSize: 10; color: "#0F172A"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                        Text { Layout.fillWidth: true; text: modelData.name; font.pixelSize: 10; color: "#0F172A"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                        Text { Layout.fillWidth: true; text: modelData.is_read ? "Read" : "Pending"; font.pixelSize: 10; font.bold: true; color: modelData.is_read ? "#10B981" : "#64748B"; verticalAlignment: Text.AlignVCenter }
                                        Text { Layout.fillWidth: true; text: modelData.is_read ? (modelData.reading_value || "-") : "-"; font.pixelSize: 10; color: "#0F172A"; verticalAlignment: Text.AlignVCenter }
                                        Button {
                                            id: btnRowPrint
                                            Layout.fillWidth: true
                                            visible: modelData.is_read
                                            text: "Print"
                                            scale: pressed ? 0.92 : 1.0
                                            Behavior on scale { NumberAnimation { duration: 80 } }
                                            background: Rectangle {
                                                radius: 8
                                                color: btnRowPrint.pressed ? "#DBEAFE" : (btnRowPrint.hovered ? "#EFF6FF" : "transparent")
                                                Behavior on color { ColorAnimation { duration: 120 } }
                                            }
                                            contentItem: Text { text: "Print"; color: "#1D4ED8"; font.pixelSize: 10; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                            onClicked: {
                                                pendingReprintConsumerId = modelData.id
                                                reprintConfirmDialog.open()
                                            }
                                        }
                                        Item { Layout.fillWidth: true; visible: !modelData.is_read }
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
