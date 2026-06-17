import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: mainContainerRoot
    width: parent ? parent.width : 480
    height: parent ? parent.height : 750
    color: "#F8FAFC"

    readonly property var bridgeObj: (typeof appBridge !== "undefined" && appBridge) ? appBridge : null
    readonly property int currentActiveTab: bridgeObj ? bridgeObj.currentTab : 0

    function showToast(message) {
        toastText.text = message
        toastPopup.open()
        toastHideTimer.restart()
    }

    Rectangle {
        id: statusBar
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 28
        color: "#0B1220"
        z: 30

        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: 12
            text: bridgeObj ? bridgeObj.statusTime : "--:--"
            color: "white"
            font.pixelSize: 11
            font.family: "Montserrat"
            font.bold: true
        }

        Text {
            anchors.centerIn: parent
            text: bridgeObj ? ("Paper: " + bridgeObj.paperStatus) : "Paper: --"
            color: "#CBD5E1"
            font.pixelSize: 10
            font.family: "Montserrat"
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 12
            text: bridgeObj ? (bridgeObj.batteryLevel + "%") : "--%"
            color: "white"
            font.pixelSize: 10
            font.family: "Montserrat"
            font.bold: true
        }
    }

    Popup {
        id: profilePopup
        x: parent.width - width - 12
        y: 76
        width: 200
        height: 136
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
                font.pixelSize: 13
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
                font.pixelSize: 10
                font.family: "Montserrat"
                color: "#64748B"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                Layout.fillWidth: true
            }

            Item { Layout.fillHeight: true }

            Button {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 152
                Layout.preferredHeight: 40
                text: "Log Out"
                scale: pressed ? 0.96 : 1.0
                Behavior on scale { NumberAnimation { duration: 80 } }
                contentItem: Text {
                    text: "Log Out"
                    color: "white"
                    font.family: "Montserrat"
                    font.pixelSize: 11
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
        width: 240
        height: 48
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
            font.pixelSize: 11
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
    }

    Rectangle {
        id: busyOverlay
        anchors.fill: parent
        color: "#80000000"
        visible: bridgeObj && bridgeObj.operationBusy
        z: 100

        Rectangle {
            anchors.centerIn: parent
            width: 180
            height: 120
            radius: 18
            color: "#111827"
            border.color: "#334155"
            border.width: 1

            ColumnLayout {
                anchors.centerIn: parent
                spacing: 10

                BusyIndicator {
                    running: bridgeObj && bridgeObj.operationBusy
                    width: 28
                    height: 28
                }

                Text {
                    text: bridgeObj ? bridgeObj.operationBusyMessage : "Working..."
                    color: "white"
                    font.family: "Montserrat"
                    font.pixelSize: 12
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    Layout.preferredWidth: 150
                    wrapMode: Text.WordWrap
                }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: 28
        spacing: 0

        Rectangle {
            id: navBar
            Layout.fillWidth: true
            height: 52
            color: "#0f172a"

            RowLayout {
                anchors.fill: parent
                spacing: 0

                Button {
                    id: tabEntry
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentItem: Text {
                        text: "Meter Entry"
                        color: currentActiveTab === 0 ? "#3B82F6" : "#94A3B8"
                        font.pixelSize: 12
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
                        color: currentActiveTab === 1 ? "#3B82F6" : "#94A3B8"
                        font.pixelSize: 12
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
                        color: currentActiveTab === 2 ? "#3B82F6" : "#94A3B8"
                        font.pixelSize: 12
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
                color: "#3B82F6"
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
            height: 48
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#2563EB" }
                GradientStop { position: 1.0; color: "#1D4ED8" }
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 8

                Image {
                    source: "../images/SLR logo 1.png"
                    Layout.preferredWidth: 26
                    Layout.preferredHeight: 26
                    fillMode: Image.PreserveAspectFit
                }

                Text {
                    text: "Water Meter Reading System"
                    color: "white"
                    font.pixelSize: 12
                    font.family: "Montserrat"
                    font.bold: true
                }

                Item { Layout.fillWidth: true }

                Rectangle {
                    width: 32
                    height: 32
                    radius: 16
                    color: "#DBEAFE"
                    scale: profilePressed ? 0.95 : 1.0

                    property bool profilePressed: false

                    Behavior on scale { NumberAnimation { duration: 80 } }

                    Text {
                        anchors.centerIn: parent
                        text: "👤"
                        font.pixelSize: 16
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
}
