import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "TouchMetrics.js" as TouchMetrics

Rectangle {
    id: mainContainerRoot
    width: parent ? parent.width : 480
    height: parent ? parent.height : 750
    color: "#F4F7FB"

    readonly property var bridgeObj: (typeof appBridge !== "undefined" && appBridge) ? appBridge : null
    readonly property int currentActiveTab: bridgeObj ? bridgeObj.currentTab : 0
    readonly property bool compactScreen: width <= 420
    readonly property int keyboardInset: appKeyboard.visibleHeight

    function showToast(message) {
        toastText.text = message
        toastPopup.open()
        toastHideTimer.restart()
    }

    function showAlert(title, message) {
        alertDialog.title = title
        alertText.text = message
        alertDialog.open()
    }

    function showReceipt(title, receipt) {
        receiptDialog.title = title
        receiptText.text = receipt
        receiptDialog.open()
    }

    function showPrintPreview(title, receipt, actionLabel) {
        previewDialog.title = title
        previewText.text = receipt
        proceedPreviewButton.text = actionLabel
        previewDialog.open()
    }

    function openPrintHistory() {
        historyDialog.open()
    }

    Rectangle {
        id: statusBar
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 32
        color: "#0B1220"
        z: 30

        Text {
            anchors.centerIn: parent
            text: bridgeObj ? bridgeObj.statusTime : "--:--"
            color: "white"
            font.pixelSize: TouchMetrics.smallText
            font.family: "Montserrat"
            font.bold: true
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 64
            text: bridgeObj ? ("PAPER " + bridgeObj.paperStatus.toUpperCase()) : "PAPER --"
            color: bridgeObj && bridgeObj.paperStatus.toLowerCase() === "ok" ? "#43A047" : "#F59E0B"
            font.pixelSize: TouchMetrics.smallText
            font.family: "Montserrat"
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 12
            text: bridgeObj ? (bridgeObj.batteryLevel + "%") : "--%"
            color: "white"
            font.pixelSize: TouchMetrics.smallText
            font.family: "Montserrat"
            font.bold: true
        }

        Row {
            anchors.left: parent.left
            anchors.leftMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3
            Repeater {
                model: 4
                Rectangle { width: 4; height: 6 + index * 3; color: "#43A047" }
            }
        }
    }

    Popup {
        id: profilePopup
        x: parent.width - width - 12
        y: 76
        width: 240
        height: 176
        modal: true
        focus: true

        background: Rectangle {
            radius: 10
            color: "white"
            border.color: "#CBD5E1"
            border.width: 1
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 7

            Text {
                text: bridgeObj ? bridgeObj.readerName : "User"
                font.pixelSize: TouchMetrics.bodyText
                font.family: "Montserrat"
                font.bold: true
                color: "#0F172A"
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                Layout.fillWidth: true
            }

            Text {
                text: bridgeObj ? ("ID: " + bridgeObj.readerId) : "ID: --"
                font.pixelSize: TouchMetrics.helperText
                font.family: "Montserrat"
                color: "#64748B"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                Layout.fillWidth: true
            }

            Item { Layout.fillHeight: true }

            Button {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 170
                Layout.preferredHeight: TouchMetrics.buttonHeight
                text: "Log Out"
                scale: pressed ? 0.96 : 1.0
                Behavior on scale { NumberAnimation { duration: 80 } }
                contentItem: Text {
                    text: "Log Out"
                    color: "white"
                    font.family: "Montserrat"
                    font.pixelSize: TouchMetrics.buttonText
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    radius: 12
                    color: parent.pressed ? "#111827" : "#333333"
                    Behavior on color { ColorAnimation { duration: 120 } }
                }
                onClicked: {
                    profilePopup.close()
                    if (bridgeObj) bridgeObj.logout()
                }
            }
        }
    }

    Popup {
        id: toastPopup
        x: (parent.width - width) / 2
        y: 40
        width: Math.min(parent.width - 32, 360)
        height: 64
        modal: false
        focus: false
        closePolicy: Popup.NoAutoClose

        background: Rectangle {
            radius: 16
            color: "#0F172A"
            border.color: "#1D4ED8"
            border.width: 1
        }

        Text {
            id: toastText
            anchors.centerIn: parent
            width: parent.width - 24
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: "white"
            font.family: "Montserrat"
            font.pixelSize: TouchMetrics.bodyText
            font.bold: true
            wrapMode: Text.WordWrap
        }
    }

    Timer {
        id: toastHideTimer
        interval: 1800
        repeat: false
        onTriggered: toastPopup.close()
    }

    Connections {
        target: bridgeObj
        function onWelcomeToastRequested(message) {
            showToast(message)
        }
        function onAlertRequested(title, message) {
            showAlert(title, message)
        }
        function onReceiptPreviewRequested(title, receipt) {
            showReceipt(title, receipt)
        }
        function onPrintPreviewRequested(title, receipt, actionLabel) {
            showPrintPreview(title, receipt, actionLabel)
        }
        function onPrintHistoryRequested() {
            openPrintHistory()
        }
    }

    Dialog {
        id: alertDialog
        anchors.centerIn: parent
        width: Math.min(parent.width - 40, 420)
        modal: true
        standardButtons: Dialog.Ok
        contentItem: Text {
            id: alertText
            width: parent.width
            wrapMode: Text.WordWrap
            color: "#111827"
            font.family: "Montserrat"
            font.pixelSize: TouchMetrics.bodyText
        }
        background: Rectangle { color: "white"; radius: 8; border.color: "#D8E1EC" }
    }

    Dialog {
        id: receiptDialog
        anchors.centerIn: parent
        width: Math.min(parent.width - 32, 440)
        height: Math.min(parent.height - 64, 620)
        modal: true
        standardButtons: Dialog.Close
        contentItem: ScrollView {
            clip: true
            TextArea {
                id: receiptText
                readOnly: true
                wrapMode: TextEdit.NoWrap
                color: "#111827"
                font.family: "Courier New"
                font.pixelSize: TouchMetrics.codeText
                background: Rectangle { color: "#F8FAFD"; radius: 6 }
            }
        }
        background: Rectangle { color: "white"; radius: 8; border.color: "#D8E1EC" }
    }

    Dialog {
        id: previewDialog
        anchors.centerIn: parent
        width: Math.min(parent.width - 24, 444)
        height: Math.min(parent.height - 48, 680)
        modal: true
        standardButtons: Dialog.NoButton

        background: Rectangle { color: "white"; radius: 8; border.color: "#D8E1EC" }

        contentItem: ColumnLayout {
            spacing: 12

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                TextArea {
                    id: previewText
                    readOnly: true
                    wrapMode: TextEdit.NoWrap
                    color: "#111827"
                    font.family: "Courier New"
                    font.pixelSize: TouchMetrics.codeText
                    background: Rectangle { color: "#F8FAFD"; radius: 6 }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Button {
                    Layout.fillWidth: true
                    implicitHeight: TouchMetrics.buttonHeight
                    text: "Cancel"
                    onClicked: {
                        if (bridgeObj) bridgeObj.cancelPrintPreview()
                        previewDialog.close()
                    }
                }

                Button {
                    id: proceedPreviewButton
                    Layout.fillWidth: true
                    implicitHeight: TouchMetrics.buttonHeight
                    enabled: bridgeObj ? !bridgeObj.printPreviewBusy : false
                    onClicked: {
                        if (bridgeObj) bridgeObj.proceedPrintPreview()
                        previewDialog.close()
                    }
                }
            }
        }
    }

    Dialog {
        id: historyDetailDialog
        anchors.centerIn: parent
        width: Math.min(parent.width - 24, 444)
        height: Math.min(parent.height - 48, 680)
        modal: true
        standardButtons: Dialog.NoButton
        title: bridgeObj ? bridgeObj.printHistoryDetailTitle : "Receipt"

        background: Rectangle { color: "white"; radius: 8; border.color: "#D8E1EC" }

        contentItem: ColumnLayout {
            spacing: 12

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                TextArea {
                    readOnly: true
                    text: bridgeObj ? bridgeObj.printHistoryDetailText : ""
                    wrapMode: TextEdit.NoWrap
                    color: "#111827"
                    font.family: "Courier New"
                    font.pixelSize: TouchMetrics.codeText
                    background: Rectangle { color: "#F8FAFD"; radius: 6 }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Button {
                    Layout.fillWidth: true
                    implicitHeight: TouchMetrics.buttonHeight
                    text: "Back"
                    onClicked: {
                        if (bridgeObj) bridgeObj.closePrintHistoryDetail()
                        historyDetailDialog.close()
                    }
                }

                Button {
                    Layout.fillWidth: true
                    implicitHeight: TouchMetrics.buttonHeight
                    text: "Reprint"
                    onClicked: {
                        if (bridgeObj) bridgeObj.reprintSelectedHistory()
                        historyDetailDialog.close()
                    }
                }
            }
        }
    }

    Dialog {
        id: historyDialog
        anchors.centerIn: parent
        width: Math.min(parent.width - 20, 452)
        height: Math.min(parent.height - 36, 700)
        modal: true
        standardButtons: Dialog.NoButton
        title: "Print History"

        background: Rectangle { color: "white"; radius: 8; border.color: "#D8E1EC" }

        contentItem: ColumnLayout {
            spacing: 12

            TextField {
                id: historySearch
                Layout.fillWidth: true
                implicitHeight: TouchMetrics.inputHeight
                placeholderText: "Search receipt, account, consumer..."
                onTextChanged: { if (bridgeObj) bridgeObj.refreshPrintHistory(text) }
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                ListView {
                    id: historyList
                    width: parent.width
                    model: bridgeObj ? bridgeObj.printHistoryRecords : []
                    spacing: 8

                    delegate: Rectangle {
                        width: historyList.width
                        height: 116
                        radius: 10
                        color: "#F8FAFD"
                        border.color: "#D8E1EC"

                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                if (bridgeObj) bridgeObj.openPrintHistoryDetail(modelData.id)
                                historyDetailDialog.open()
                            }
                        }

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 4

                            Text {
                                text: "Receipt #" + modelData.receipt_number + " • " + (modelData.print_action === "reprint" ? "Reprint" : "Original")
                                font.family: "Montserrat"
                                font.pixelSize: TouchMetrics.bodyText
                                font.bold: true
                                color: "#0F172A"
                            }
                            Text {
                                text: modelData.consumer_name
                                font.family: "Montserrat"
                                font.pixelSize: TouchMetrics.bodyText
                                color: "#111827"
                                elide: Text.ElideRight
                            }
                            Text {
                                text: "Acct: " + modelData.account_number
                                font.family: "Montserrat"
                                font.pixelSize: TouchMetrics.helperText
                                color: "#526176"
                            }
                            Text {
                                text: "Printed: " + modelData.printed_at
                                font.family: "Montserrat"
                                font.pixelSize: TouchMetrics.helperText
                                color: "#526176"
                            }
                            Text {
                                text: "Prints: " + modelData.print_count + " • Reprints: " + modelData.reprint_count + " • By: " + modelData.printed_by
                                font.family: "Montserrat"
                                font.pixelSize: TouchMetrics.helperText
                                color: "#526176"
                                wrapMode: Text.Wrap
                            }
                        }
                    }
                }
            }

            Button {
                Layout.fillWidth: true
                implicitHeight: TouchMetrics.buttonHeight
                text: "Close"
                onClicked: historyDialog.close()
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: statusBar.height
        spacing: 0

        Rectangle {
            id: navBar
            Layout.fillWidth: true
            height: mainContainerRoot.compactScreen ? TouchMetrics.compactNavHeight : 70
            color: "#111827"

            RowLayout {
                anchors.fill: parent
                spacing: 0

                Button {
                    id: tabEntry
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentItem: Text {
                        text: "Meter Entry"
                        color: currentActiveTab === 0 ? "#FFFFFF" : "#A8B4C5"
                        font.pixelSize: mainContainerRoot.compactScreen ? TouchMetrics.compactTabText : TouchMetrics.tabText
                        font.family: "Montserrat"
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle { color: tabEntry.hovered ? "#1E293B" : "transparent" }
                    onClicked: { if (bridgeObj) bridgeObj.currentTab = 0 }
                }

                Button {
                    id: tabProgress
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentItem: Text {
                        text: "Progress"
                        color: currentActiveTab === 1 ? "#FFFFFF" : "#A8B4C5"
                        font.pixelSize: mainContainerRoot.compactScreen ? TouchMetrics.compactTabText : TouchMetrics.tabText
                        font.family: "Montserrat"
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle { color: tabProgress.hovered ? "#1E293B" : "transparent" }
                    onClicked: { if (bridgeObj) bridgeObj.currentTab = 1 }
                }

                Button {
                    id: tabSettings
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentItem: Text {
                        text: "Settings"
                        color: currentActiveTab === 2 ? "#FFFFFF" : "#A8B4C5"
                        font.pixelSize: mainContainerRoot.compactScreen ? TouchMetrics.compactTabText : TouchMetrics.tabText
                        font.family: "Montserrat"
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle { color: tabSettings.hovered ? "#1E293B" : "transparent" }
                    onClicked: { if (bridgeObj) bridgeObj.currentTab = 2 }
                }
            }

            Rectangle {
                id: tabIndicator
                y: parent.height - 3
                height: 3
                color: "#60A5FA"
                z: 10

                property var activeBtn: {
                    if (currentActiveTab === 0) return tabEntry
                    if (currentActiveTab === 1) return tabProgress
                    if (currentActiveTab === 2) return tabSettings
                    return tabEntry
                }

                x: activeBtn ? activeBtn.x : 0
                width: activeBtn ? activeBtn.width : 0

                Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                Behavior on width { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: mainContainerRoot.compactScreen ? TouchMetrics.compactTopBarHeight : TouchMetrics.topBarHeight
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#2563EB" }
                GradientStop { position: 1.0; color: "#1D4ED8" }
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 12

                Image {
                    source: "../images/SLR logo 1.png"
                    Layout.preferredWidth: 34
                    Layout.preferredHeight: 34
                    fillMode: Image.PreserveAspectFit
                }

                Text {
                    text: "Water Meter Reading System"
                    color: "white"
                    font.pixelSize: mainContainerRoot.compactScreen ? TouchMetrics.bodyText : 18
                    font.family: "Montserrat"
                    font.bold: true
                }

                Item { Layout.fillWidth: true }

                Text {
                    text: bridgeObj ? bridgeObj.readerName : "User"
                    color: "white"
                    font.family: "Montserrat"
                    font.pixelSize: mainContainerRoot.compactScreen ? TouchMetrics.helperText : TouchMetrics.bodyText
                    font.bold: true
                }

                Rectangle {
                    width: TouchMetrics.iconButtonSize
                    height: TouchMetrics.iconButtonSize
                    radius: TouchMetrics.iconButtonSize / 2
                    color: "#DBEAFE"
                    scale: profilePressed ? 0.95 : 1.0

                    property bool profilePressed: false

                    Behavior on scale { NumberAnimation { duration: 80 } }

                    Text {
                        anchors.centerIn: parent
                        text: "U"
                        color: "#1E40AF"
                        font.pixelSize: TouchMetrics.bodyText
                        font.family: "Montserrat"
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        onPressed: parent.profilePressed = true
                        onReleased: parent.profilePressed = false
                        onCanceled: parent.profilePressed = false
                        onClicked: profilePopup.open()
                    }
                }
            }
        }

        StackLayout {
            id: contentStack
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.bottomMargin: mainContainerRoot.keyboardInset
            currentIndex: currentActiveTab

            Loader {
                source: "MeterEntry.qml"
                Layout.fillWidth: true
                Layout.fillHeight: true
            }

            Loader {
                source: "ZoneOverview.qml"
                Layout.fillWidth: true
                Layout.fillHeight: true
            }

            Loader {
                source: "Settings.qml"
                Layout.fillWidth: true
                Layout.fillHeight: true
            }
        }
    }

    KeyboardPanel {
        id: appKeyboard
    }

    Rectangle {
        id: busyOverlay
        anchors.fill: parent
        color: "#80000000"
        visible: bridgeObj && bridgeObj.operationBusy
        z: 100

        Rectangle {
            anchors.centerIn: parent
            width: 220
            height: 150
            radius: 18
            color: "#111827"
            border.color: "#334155"
            border.width: 1

            ColumnLayout {
                anchors.centerIn: parent
                width: parent.width - 32
                spacing: 10

                BusyIndicator {
                    running: bridgeObj && bridgeObj.operationBusy
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 36
                    Layout.preferredHeight: 36
                }

                Text {
                    text: bridgeObj ? bridgeObj.operationBusyMessage : "Working..."
                    color: "white"
                    font.family: "Montserrat"
                    font.pixelSize: TouchMetrics.bodyText
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}
