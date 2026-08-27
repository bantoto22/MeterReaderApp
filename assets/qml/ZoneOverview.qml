import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "TouchMetrics.js" as TouchMetrics

Rectangle {
    id: progressRoot
    color: "#F8FAFC"

    readonly property var bridgeObj: (typeof appBridge !== "undefined" && appBridge) ? appBridge : null
    readonly property real compPercent: bridgeObj ? bridgeObj.zoneCompletionPercentage : 0.0
    readonly property bool compactScreen: width <= 420
    property int pendingReprintConsumerId: -1
    property string pendingReprintScheduleId: ""

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
                bridgeObj.reprintZoneConsumer(pendingReprintConsumerId, pendingReprintScheduleId)
            }
            pendingReprintConsumerId = -1
            pendingReprintScheduleId = ""
        }
        onRejected: {
            pendingReprintConsumerId = -1
            pendingReprintScheduleId = ""
        }
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
                            text: bridgeObj && bridgeObj.selectedRouteIsPast ? "OVERDUE FIELD ROUTE" : "Current / upcoming routes"
                            font.pixelSize: TouchMetrics.bodyText
                            font.family: "Montserrat"
                            font.bold: true
                            color: bridgeObj && bridgeObj.selectedRouteIsPast ? "#B91C1C" : "#334155"
                        }

                        ComboBox {
                            id: cmbProgressZone
                            Layout.fillWidth: true
                            visible: bridgeObj && !bridgeObj.selectedRouteIsPast
                            textRole: "label"
                            valueRole: "scheduleId"
                            model: bridgeObj ? bridgeObj.assignedRoutes : []
                            currentIndex: {
                                if (!bridgeObj) return -1
                                var ids = bridgeObj.assignedRoutes.map(function(route) { return route.scheduleId })
                                return ids.indexOf(bridgeObj.selectedRouteId)
                            }

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
                                text: modelData.label
                                highlighted: cmbProgressZone.highlightedIndex === index
                            }

                            onActivated: {
                                if (bridgeObj && currentValue) {
                                    bridgeObj.selectedRouteId = currentValue
                                }
                            }
                        }

                        Button {
                            id: btnReturnToCurrentRoute
                            Layout.fillWidth: true
                            implicitHeight: TouchMetrics.buttonHeight
                            visible: bridgeObj && bridgeObj.selectedRouteIsPast
                            enabled: bridgeObj && bridgeObj.assignedRoutes.length > 0

                            background: Rectangle {
                                radius: 8
                                color: btnReturnToCurrentRoute.enabled ? (btnReturnToCurrentRoute.pressed ? "#1D4ED8" : "#2563EB") : "#CBD5E1"
                            }
                            contentItem: Text {
                                text: btnReturnToCurrentRoute.enabled ? "Return to current route" : "No current or upcoming route"
                                color: "white"
                                font.family: "Montserrat"
                                font.pixelSize: TouchMetrics.bodyText
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: {
                                if (bridgeObj && bridgeObj.assignedRoutes.length > 0) {
                                    bridgeObj.selectedRouteId = bridgeObj.assignedRoutes[0].scheduleId
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            visible: bridgeObj && (bridgeObj.pastRoutes.length > 1 || (bridgeObj.pastRoutes.length === 1 && !bridgeObj.selectedRouteIsPast))

                            Text {
                                text: bridgeObj && bridgeObj.pastRoutes.length > 1 ? "Past schedules" : "Missed schedule"
                                font.pixelSize: TouchMetrics.helperText
                                font.family: "Montserrat"
                                font.bold: true
                                color: "#64748B"
                            }

                            ComboBox {
                                id: cmbPastRoute
                                Layout.fillWidth: true
                                visible: bridgeObj && bridgeObj.pastRoutes.length > 1
                                textRole: "label"
                                valueRole: "scheduleId"
                                model: bridgeObj ? bridgeObj.pastRoutes : []
                                currentIndex: {
                                    if (!bridgeObj || !bridgeObj.selectedRouteIsPast) return -1
                                    var ids = bridgeObj.pastRoutes.map(function(route) { return route.scheduleId })
                                    return ids.indexOf(bridgeObj.selectedRouteId)
                                }
                                displayText: currentIndex >= 0 ? currentText : "Open a missed schedule..."

                                background: Rectangle {
                                    implicitHeight: TouchMetrics.buttonHeight
                                    radius: 8
                                    border.color: cmbPastRoute.focus ? "#DC2626" : "#FCA5A5"
                                    border.width: 1
                                    color: "#FFF7F7"
                                }
                                contentItem: Text {
                                    text: cmbPastRoute.displayText
                                    font.family: "Montserrat"
                                    font.pixelSize: TouchMetrics.bodyText
                                    color: "#7F1D1D"
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: 10
                                    elide: Text.ElideRight
                                }
                                delegate: ItemDelegate {
                                    width: cmbPastRoute.width
                                    text: modelData.label
                                    highlighted: cmbPastRoute.highlightedIndex === index
                                }
                                onActivated: {
                                    if (bridgeObj && currentValue) bridgeObj.selectedRouteId = currentValue
                                }
                            }

                            Button {
                                id: btnSinglePastRoute
                                Layout.fillWidth: true
                                implicitHeight: TouchMetrics.buttonHeight
                                visible: bridgeObj && bridgeObj.pastRoutes.length === 1 && !bridgeObj.selectedRouteIsPast

                                background: Rectangle {
                                    radius: 8
                                    color: btnSinglePastRoute.pressed ? "#FEE2E2" : "#FFF7F7"
                                    border.color: "#FCA5A5"
                                    border.width: 1
                                }
                                contentItem: Text {
                                    text: bridgeObj && bridgeObj.pastRoutes.length === 1 ? ("Open " + bridgeObj.pastRoutes[0].label) : "Open missed schedule"
                                    color: "#7F1D1D"
                                    font.family: "Montserrat"
                                    font.pixelSize: TouchMetrics.bodyText
                                    font.bold: true
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                                onClicked: {
                                    if (bridgeObj && bridgeObj.pastRoutes.length === 1) {
                                        bridgeObj.selectedRouteId = bridgeObj.pastRoutes[0].scheduleId
                                    }
                                }
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4

                            Text {
                                text: "Zone filter"
                                font.pixelSize: TouchMetrics.helperText
                                font.family: "Montserrat"
                                font.bold: true
                                color: "#64748B"
                            }

                            ComboBox {
                                id: cmbGroupedZone
                                Layout.fillWidth: true
                                model: bridgeObj ? bridgeObj.zones : []
                                currentIndex: bridgeObj ? Math.max(0, bridgeObj.zones.indexOf(bridgeObj.selectedZone)) : 0
                                background: Rectangle {
                                    implicitHeight: TouchMetrics.buttonHeight
                                    radius: 8
                                    border.color: cmbGroupedZone.focus ? "#3B82F6" : "#E2E8F0"
                                    color: "#F8FAFC"
                                }
                                contentItem: Text {
                                    text: cmbGroupedZone.currentText
                                    font.family: "Montserrat"
                                    font.pixelSize: TouchMetrics.bodyText
                                    color: "#0F172A"
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: 10
                                }
                                onActivated: {
                                    if (bridgeObj && currentText) bridgeObj.selectedZone = currentText
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: bridgeObj ? ("Reading month: " + bridgeObj.selectedRouteBillingMonth + "  |  " + bridgeObj.selectedRoutePeriod) : ""
                            font.pixelSize: TouchMetrics.helperText
                            font.family: "Montserrat"
                            color: "#64748B"
                            wrapMode: Text.WordWrap
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Rectangle {
                                Layout.preferredWidth: routeReadyText.implicitWidth + 24
                                Layout.preferredHeight: 32
                                radius: 16
                                color: bridgeObj && bridgeObj.routeOfflineReady ? "#DCFCE7" : "#FEF3C7"
                                border.color: bridgeObj && bridgeObj.routeOfflineReady ? "#86EFAC" : "#FCD34D"
                                Text {
                                    id: routeReadyText
                                    anchors.centerIn: parent
                                    text: bridgeObj ? bridgeObj.routeCacheMessage : ""
                                    font.pixelSize: TouchMetrics.helperText
                                    font.family: "Montserrat"
                                    font.bold: true
                                    color: bridgeObj && bridgeObj.routeOfflineReady ? "#166534" : "#92400E"
                                }
                            }

                            Item { Layout.fillWidth: true }

                            Rectangle {
                                Layout.preferredWidth: pendingSyncText.implicitWidth + 22
                                Layout.preferredHeight: 32
                                radius: 16
                                color: bridgeObj && bridgeObj.syncPendingCount > 0 ? "#FFF7ED" : "#EFF6FF"
                                border.color: bridgeObj && bridgeObj.syncPendingCount > 0 ? "#FDBA74" : "#BFDBFE"
                                Text {
                                    id: pendingSyncText
                                    anchors.centerIn: parent
                                    text: bridgeObj ? (bridgeObj.syncPendingCount + " pending sync") : "0 pending sync"
                                    font.pixelSize: TouchMetrics.helperText
                                    font.family: "Montserrat"
                                    font.bold: true
                                    color: bridgeObj && bridgeObj.syncPendingCount > 0 ? "#9A3412" : "#1D4ED8"
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: bridgeObj ? ("Status: " + bridgeObj.selectedRouteStatus) : ""
                            font.pixelSize: TouchMetrics.helperText
                            font.family: "Montserrat"
                            font.bold: true
                            color: bridgeObj && bridgeObj.selectedRouteStatus === "Overdue" ? "#DC2626" : "#475569"
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: carryOverText.implicitHeight + 18
                            radius: 8
                            visible: bridgeObj && bridgeObj.selectedRouteCarryOverCount > 0
                            color: "#FEF2F2"
                            border.color: "#FCA5A5"

                            Text {
                                id: carryOverText
                                anchors.fill: parent
                                anchors.margins: 9
                                text: bridgeObj ? (bridgeObj.selectedRouteCarryOverCount + " expired unread assignment" + (bridgeObj.selectedRouteCarryOverCount === 1 ? " is" : "s are") + " included in this route") : ""
                                font.pixelSize: TouchMetrics.helperText
                                font.family: "Montserrat"
                                font.bold: true
                                color: "#B91C1C"
                                wrapMode: Text.WordWrap
                                verticalAlignment: Text.AlignVCenter
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
                                        text: "Route Progress"
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
                                contentItem: Text { text: "Sync Now"; color: "#2563EB"; font.family: "Montserrat"; font.pixelSize: TouchMetrics.bodyText; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
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
                        readonly property real meterColumnWidth: columnsWidth * 0.23
                        readonly property real nameColumnWidth: columnsWidth * 0.23
                        readonly property real statusColumnWidth: columnsWidth * 0.14
                        readonly property real readingColumnWidth: columnsWidth * 0.14
                        readonly property real actionColumnWidth: columnsWidth * 0.26
                        implicitHeight: Math.min(560, Math.max(160, 58 + rowCount * TouchMetrics.tableRowHeight))

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Rectangle { Layout.preferredWidth: detailsTable.meterColumnWidth; Layout.preferredHeight: TouchMetrics.tableHeaderHeight; color: "#E2E8F0"; Text { anchors.centerIn: parent; text: "Account"; font.family: "Montserrat"; font.bold: true; color: "#64748B"; font.pixelSize: TouchMetrics.helperText } }
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

                                        ColumnLayout {
                                            Layout.preferredWidth: detailsTable.meterColumnWidth
                                            spacing: 0
                                            Text { Layout.fillWidth: true; text: modelData.acct_no; font.family: "Montserrat"; font.pixelSize: TouchMetrics.helperText; font.bold: true; color: "#0F172A"; elide: Text.ElideRight; leftPadding: 8 }
                                            Text { Layout.fillWidth: true; text: modelData.is_nearby_connection ? "Nearby connections" : ("Meter " + modelData.meter_no); font.family: "Montserrat"; font.pixelSize: 9; color: modelData.is_nearby_connection ? "#2563EB" : "#64748B"; elide: Text.ElideRight; leftPadding: 8 }
                                        }
                                        ColumnLayout {
                                            Layout.preferredWidth: detailsTable.nameColumnWidth
                                            spacing: 0
                                            Text { Layout.fillWidth: true; text: modelData.name; font.family: "Montserrat"; font.pixelSize: TouchMetrics.helperText; color: "#0F172A"; elide: Text.ElideRight; leftPadding: 8 }
                                            Text {
                                                Layout.fillWidth: true
                                                text: modelData.schedule_date ? ("Scheduled " + modelData.schedule_date + ((modelData.schedule_due_date && modelData.schedule_due_date !== modelData.schedule_date) ? " • Due " + modelData.schedule_due_date : "")) : ""
                                                font.family: "Montserrat"; font.pixelSize: 9; color: "#64748B"; elide: Text.ElideRight; leftPadding: 8
                                            }
                                        }
                                        Text {
                                            Layout.preferredWidth: detailsTable.statusColumnWidth
                                            text: modelData.is_read ? (modelData.reading_sync_status === "synced" ? "Completed" : "Saved") : (modelData.deadline_status || "Pending")
                                            font.family: "Montserrat"; font.pixelSize: TouchMetrics.helperText; font.bold: true
                                            color: modelData.is_read ? "#10B981" : ((modelData.deadline_status || "").indexOf("Overdue") === 0 ? "#DC2626" : ((modelData.deadline_status || "") !== "Pending" ? "#D97706" : "#64748B"))
                                            verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                                        }
                                        Text { Layout.preferredWidth: detailsTable.readingColumnWidth; text: modelData.is_read ? (modelData.reading_value || "-") : "-"; font.family: "Montserrat"; font.pixelSize: TouchMetrics.helperText; color: "#0F172A"; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter }
                                        RowLayout {
                                            Layout.preferredWidth: detailsTable.actionColumnWidth
                                            Layout.fillHeight: true
                                            spacing: 2

                                            Button {
                                                id: btnRowPrint
                                                Layout.fillWidth: true
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
                                                    pendingReprintScheduleId = String(modelData.schedule_id || "")
                                                    reprintConfirmDialog.open()
                                                }
                                            }

                                            Button {
                                                id: btnRowNewBill
                                                Layout.fillWidth: true
                                                Layout.fillHeight: true
                                                text: modelData.is_read ? "New" : "Read"
                                                scale: pressed ? 0.92 : 1.0
                                                Behavior on scale { NumberAnimation { duration: 80 } }
                                                background: Rectangle {
                                                    radius: 8
                                                    color: btnRowNewBill.pressed ? "#DCFCE7" : (btnRowNewBill.hovered ? "#F0FDF4" : "transparent")
                                                    Behavior on color { ColorAnimation { duration: 120 } }
                                                }
                                                contentItem: Text { text: modelData.is_read ? "New" : "Read"; color: "#047857"; font.pixelSize: TouchMetrics.helperText; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                                onClicked: {
                                                    if (bridgeObj) bridgeObj.startNewBillForZoneConsumer(modelData.id, String(modelData.schedule_id || ""))
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
    }
}
