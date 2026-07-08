import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects
import "TouchMetrics.js" as TouchMetrics

Rectangle {
    id: progressRoot
    color: "#F8FAFC"

    readonly property var bridgeObj: (typeof appBridge !== "undefined" && appBridge) ? appBridge : null
    readonly property real compPercent: bridgeObj ? bridgeObj.zoneCompletionPercentage : 0.0
    readonly property bool compactScreen: width <= 420
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
            ScrollablePage {
                anchors.fill: parent
                maxContentWidth: 440

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: TouchMetrics.sectionSpacing

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Text {
                            text: "Assigned Zone"
                            font.pixelSize: TouchMetrics.bodyText
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
                                implicitHeight: TouchMetrics.buttonHeight
                                radius: 8
                                border.color: cmbProgressZone.focus ? "#3B82F6" : "#E2E8F0"
                                border.width: 1
                                color: "#F8FAFC"
                            }

                            contentItem: Text {
                                text: cmbProgressZone.currentText
                                font.family: "Montserrat"
                                font.pixelSize: TouchMetrics.bodyText
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
                        implicitHeight: progressCardContent.implicitHeight + (progressRoot.compactScreen ? 28 : 40)
                        radius: 8
                        color: "#1F4FC4"
                        border.color: "#1F4FC4"
                        border.width: 1
                        clip: true
                        
                        layer.enabled: true
                        layer.effect: MultiEffect {
                            shadowEnabled: true
                            shadowBlur: 0.8
                            shadowHorizontalOffset: 0
                            shadowVerticalOffset: 4
                            shadowColor: "#20000000"
                        }

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
                                visible: false
                                Layout.fillWidth: true
                                Layout.preferredHeight: 0
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
                                Layout.margins: 0
                                radius: 8
                                clip: true
                                gradient: Gradient {
                                    GradientStop { position: 0.0; color: "#2563EB" }
                                    GradientStop { position: 1.0; color: "#1D4ED8" }
                                }

                                ColumnLayout {
                                    id: progressCardContent
                                    anchors.fill: parent
                                    anchors.margins: progressRoot.compactScreen ? 14 : 20
                                    spacing: progressRoot.compactScreen ? 10 : 12

                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: "Today's Progress"
                                        color: "white"
                                        font.pixelSize: TouchMetrics.bodyText
                                        font.family: "Montserrat"
                                        font.bold: true
                                        font.letterSpacing: 1.2
                                    }

                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: bridgeObj ? bridgeObj.zoneReadFraction : "0/0"
                                        color: "white"
                                        font.pixelSize: 56
                                        font.family: "Montserrat"
                                        font.bold: true
                                    }

                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: "Meters Read"
                                        color: "#93C5FD"
                                        font.pixelSize: TouchMetrics.bodyText
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
                                            radius: 0
                                            color: "transparent"
                                            border.width: 0

                                            ColumnLayout {
                                                anchors.centerIn: parent
                                                spacing: 2
                                                Text {
                                                    Layout.alignment: Qt.AlignHCenter
                                                    text: bridgeObj ? bridgeObj.zoneRemainingCount : "0"
                                                    color: "white"
                                                    font.pixelSize: 28
                                                    font.family: "Montserrat"
                                                    font.bold: true
                                                }
                                                Text {
                                                    Layout.alignment: Qt.AlignHCenter
                                                    text: "Remaining"
                                                    color: "#93C5FD"
                                                    font.pixelSize: TouchMetrics.helperText
                                                    font.family: "Montserrat"
                                                }
                                            }
                                        }

                                        Rectangle {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 74
                                            radius: 0
                                            color: "transparent"
                                            border.width: 0

                                            ColumnLayout {
                                                anchors.centerIn: parent
                                                spacing: 2
                                                Text {
                                                    Layout.alignment: Qt.AlignHCenter
                                                    text: bridgeObj ? bridgeObj.zoneFlaggedCount : "0"
                                                    color: "#FBBF24"
                                                    font.pixelSize: 28
                                                    font.family: "Montserrat"
                                                    font.bold: true
                                                }
                                                Text {
                                                    Layout.alignment: Qt.AlignHCenter
                                                    text: "Flagged"
                                                    color: "#93C5FD"
                                                    font.pixelSize: TouchMetrics.helperText
                                                    font.family: "Montserrat"
                                                }
                                            }
                                        }
                                    }

                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: "Tap for details"
                                        color: "#93C5FD"
                                        font.pixelSize: TouchMetrics.helperText
                                        font.family: "Montserrat"
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: zoneSummaryContent.implicitHeight + (progressRoot.compactScreen ? 26 : 36)
                        radius: 8
                        color: "white"
                        border.color: "#D8E1EC"

                        RowLayout {
                            id: zoneSummaryContent
                            anchors.fill: parent
                            anchors.margins: progressRoot.compactScreen ? 16 : 26
                            ColumnLayout {
                                spacing: 5
                                Text { text: bridgeObj ? bridgeObj.selectedZone : "-"; color: "#111827"; font.family: "Montserrat"; font.pixelSize: TouchMetrics.pageTitle; font.bold: true }
                                Text { text: (bridgeObj ? bridgeObj.zoneReadFraction.split("/")[1] : "0") + " households assigned"; color: "#526176"; font.family: "Montserrat"; font.pixelSize: TouchMetrics.helperText }
                                RowLayout {
                                    spacing: 10
                                    Text { text: (bridgeObj ? bridgeObj.zoneCompletionPercentage : 0) + "%"; color: "#10B981"; font.family: "Montserrat"; font.pixelSize: 34; font.bold: true }
                                    Text { text: "Complete"; color: "#526176"; font.family: "Montserrat"; font.pixelSize: TouchMetrics.helperText; font.bold: true; Layout.alignment: Qt.AlignBottom }
                                }
                            }
                            Item { Layout.fillWidth: true }
                            Button {
                                implicitWidth: 140
                                implicitHeight: TouchMetrics.buttonHeight
                                contentItem: Text { text: "Manual Sync"; color: "#2563EB"; font.family: "Montserrat"; font.pixelSize: TouchMetrics.bodyText; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                background: Rectangle { radius: 7; color: parent.hovered ? "#DBEAFE" : "white"; border.color: "#BFDBFE" }
                                onClicked: { if (bridgeObj) bridgeObj.syncNow() }
                            }
                        }
                    }
                }
            }
        }

        Item {
            ScrollablePage {
                anchors.fill: parent
                maxContentWidth: 450
                pageSidePadding: width <= 420 ? 10 : 15
                pageTopPadding: 12

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: TouchMetrics.sectionSpacing

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: progressRoot.compactScreen ? 46 : 50
                        radius: 12
                        clip: true
                        color: "#1D4ED8"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 12

                            Button {
                                id: btnBackDetails
                                implicitWidth: TouchMetrics.iconButtonSize
                                implicitHeight: TouchMetrics.iconButtonSize
                                scale: pressed ? 0.92 : 1.0
                                Behavior on scale { NumberAnimation { duration: 80 } }
                                text: "<"
                                background: Rectangle { color: "transparent" }
                                contentItem: Text {
                                    text: "<"
                                    color: "white"
                                    font.pixelSize: TouchMetrics.buttonText
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
                                font.pixelSize: 18
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                            }

                            Item { Layout.preferredWidth: 42 }
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
                            font.pixelSize: TouchMetrics.bodyText
                            font.bold: true
                            color: "#0F172A"
                        }
                    }

                    Rectangle {
                        id: detailsTable
                        Layout.fillWidth: true
                        radius: 14
                        color: "white"
                        border.color: "#CBD5E1"
                        border.width: 1
                        readonly property int rowCount: bridgeObj ? bridgeObj.zoneConsumers.length : 0
                        readonly property real columnsWidth: Math.max(0, width - 16 - 32)
                        readonly property real meterColumnWidth: columnsWidth * 0.18
                        readonly property real nameColumnWidth: columnsWidth * 0.34
                        readonly property real statusColumnWidth: columnsWidth * 0.16
                        readonly property real readingColumnWidth: columnsWidth * 0.16
                        readonly property real actionColumnWidth: columnsWidth * 0.16
                        implicitHeight: Math.min(560, Math.max(160, 58 + rowCount * TouchMetrics.tableRowHeight))

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Rectangle { Layout.preferredWidth: detailsTable.meterColumnWidth; Layout.preferredHeight: TouchMetrics.tableHeaderHeight; color: "#E2E8F0"; Text { anchors.centerIn: parent; text: "Meter"; font.family: "Montserrat"; font.bold: true; color: "#64748B"; font.pixelSize: TouchMetrics.helperText } }
                                Rectangle { Layout.preferredWidth: detailsTable.nameColumnWidth; Layout.preferredHeight: TouchMetrics.tableHeaderHeight; color: "#E2E8F0"; Text { anchors.centerIn: parent; text: "Name"; font.family: "Montserrat"; font.bold: true; color: "#64748B"; font.pixelSize: TouchMetrics.helperText } }
                                Rectangle { Layout.preferredWidth: detailsTable.statusColumnWidth; Layout.preferredHeight: TouchMetrics.tableHeaderHeight; color: "#E2E8F0"; Text { anchors.centerIn: parent; text: "Status"; font.family: "Montserrat"; font.bold: true; color: "#64748B"; font.pixelSize: TouchMetrics.helperText } }
                                Rectangle { Layout.preferredWidth: detailsTable.readingColumnWidth; Layout.preferredHeight: TouchMetrics.tableHeaderHeight; color: "#E2E8F0"; Text { anchors.centerIn: parent; text: "Reading"; font.family: "Montserrat"; font.bold: true; color: "#64748B"; font.pixelSize: TouchMetrics.helperText } }
                                Rectangle { Layout.preferredWidth: detailsTable.actionColumnWidth; Layout.preferredHeight: TouchMetrics.tableHeaderHeight; color: "#E2E8F0"; Text { anchors.centerIn: parent; text: "Action"; font.family: "Montserrat"; font.bold: true; color: "#64748B"; font.pixelSize: TouchMetrics.helperText } }
                            }

                            ListView {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                model: bridgeObj ? bridgeObj.zoneConsumers : []
                                spacing: 1

                                delegate: Rectangle {
                                    width: ListView.view.width
                                    height: TouchMetrics.tableRowHeight
                                    color: modelData.is_read ? "#E8F5E9" : "white"

                                    RowLayout {
                                        anchors.fill: parent
                                        spacing: 8

                                        Text { Layout.preferredWidth: detailsTable.meterColumnWidth; text: modelData.meter_no; font.family: "Montserrat"; font.pixelSize: TouchMetrics.helperText; color: "#0F172A"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter; leftPadding: 8 }
                                        Text { Layout.preferredWidth: detailsTable.nameColumnWidth; text: modelData.name; font.family: "Montserrat"; font.pixelSize: TouchMetrics.helperText; color: "#0F172A"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignLeft; leftPadding: 8 }
                                        Text { Layout.preferredWidth: detailsTable.statusColumnWidth; text: modelData.is_read ? "Read" : "Pending"; font.family: "Montserrat"; font.pixelSize: TouchMetrics.helperText; font.bold: true; color: modelData.is_read ? "#10B981" : "#64748B"; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter }
                                        Text { Layout.preferredWidth: detailsTable.readingColumnWidth; text: modelData.is_read ? (modelData.reading_value || "-") : "-"; font.family: "Montserrat"; font.pixelSize: TouchMetrics.helperText; color: "#0F172A"; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter }
                                        Button {
                                            id: btnRowPrint
                                            Layout.preferredWidth: detailsTable.actionColumnWidth
                                            Layout.fillHeight: true
                                            visible: modelData.is_read
                                            text: "Print"
                                            scale: pressed ? 0.92 : 1.0
                                            Behavior on scale { NumberAnimation { duration: 80 } }
                                            background: Rectangle {
                                                radius: 8
                                                color: btnRowPrint.pressed ? "#DBEAFE" : (btnRowPrint.hovered ? "#EFF6FF" : "transparent")
                                                Behavior on color { ColorAnimation { duration: 120 } }
                                            }
                                            contentItem: Text { text: "Print"; color: "#1D4ED8"; font.pixelSize: TouchMetrics.helperText; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                            onClicked: {
                                                pendingReprintConsumerId = modelData.id
                                                reprintConfirmDialog.open()
                                            }
                                        }
                                        Text {
                                            Layout.preferredWidth: detailsTable.actionColumnWidth
                                            visible: !modelData.is_read
                                            text: "-"
                                            color: "#64748B"
                                            font.family: "Montserrat"
                                            font.pixelSize: TouchMetrics.helperText
                                            horizontalAlignment: Text.AlignHCenter
                                            verticalAlignment: Text.AlignVCenter
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
