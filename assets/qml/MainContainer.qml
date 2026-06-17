import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: mainContainerRoot
    width: parent ? parent.width : 480
    height: parent ? parent.height : 750
    color: "#F8FAFC"

    // Safe reference to appBridge
    readonly property var bridgeObj: (typeof appBridge !== "undefined" && appBridge) ? appBridge : null
    readonly property int currentActiveTab: bridgeObj ? bridgeObj.currentTab : 0

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Tab Navigation Bar
        Rectangle {
            id: navBar
            Layout.fillWidth: true
            height: 52
            color: "#0f172a"

            // Row for tab buttons
            RowLayout {
                id: tabRow
                anchors.fill: parent
                spacing: 0

                // Tab 1: Meter Entry
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
                        Behavior on color { ColorAnimation { duration: 120 } }
                    }
                    background: Rectangle {
                        color: tabEntry.hovered ? "#1E293B" : "transparent"
                        Behavior on color { ColorAnimation { duration: 120 } }
                    }
                    onClicked: { if (bridgeObj) bridgeObj.currentTab = 0 }
                }

                // Tab 2: Progress
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
                        Behavior on color { ColorAnimation { duration: 120 } }
                    }
                    background: Rectangle {
                        color: tabProgress.hovered ? "#1E293B" : "transparent"
                        Behavior on color { ColorAnimation { duration: 120 } }
                    }
                    onClicked: { if (bridgeObj) bridgeObj.currentTab = 1 }
                }

                // Tab 3: Settings
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
                        Behavior on color { ColorAnimation { duration: 120 } }
                    }
                    background: Rectangle {
                        color: tabSettings.hovered ? "#1E293B" : "transparent"
                        Behavior on color { ColorAnimation { duration: 120 } }
                    }
                    onClicked: { if (bridgeObj) bridgeObj.currentTab = 2 }
                }
            }

            // Sliding active tab indicator line (placed OUTSIDE RowLayout for absolute rendering)
            Rectangle {
                id: tabIndicator
                y: parent.height - 3
                height: 3
                color: "#3B82F6"
                z: 10

                // Calculate target x and width based on selected tab
                property var activeBtn: {
                    if (currentActiveTab === 0) return tabEntry
                    if (currentActiveTab === 1) return tabProgress
                    if (currentActiveTab === 2) return tabSettings
                    return tabEntry
                }

                x: activeBtn ? activeBtn.x : 0
                width: activeBtn ? activeBtn.width : 0

                // Snappy transition animations
                Behavior on x {
                    NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
                }
                Behavior on width {
                    NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
                }
            }
        }

        // Sub-header bar (Premium Blue Gradient)
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
            }
        }

        // Tab Content Area
        StackLayout {
            id: contentStack
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: currentActiveTab

            // Page 0: Meter Entry
            Loader {
                id: meterEntryLoader
                source: "MeterEntry.qml"
                Layout.fillWidth: true
                Layout.fillHeight: true
                
                // Snappy fade-in animation on loaded
                onLoaded: opacityAnim.start()
                opacity: 0.0
                NumberAnimation on opacity {
                    id: opacityAnim
                    to: 1.0
                    duration: 120
                    easing.type: Easing.OutQuad
                }
            }

            // Page 1: Progress
            Loader {
                id: progressLoader
                source: "ZoneOverview.qml"
                Layout.fillWidth: true
                Layout.fillHeight: true
                
                onLoaded: opacityAnimProgress.start()
                opacity: 0.0
                NumberAnimation on opacity {
                    id: opacityAnimProgress
                    to: 1.0
                    duration: 120
                    easing.type: Easing.OutQuad
                }
            }

            // Page 2: Settings
            Loader {
                id: settingsLoader
                source: "Settings.qml"
                Layout.fillWidth: true
                Layout.fillHeight: true
                
                onLoaded: opacityAnimSettings.start()
                opacity: 0.0
                NumberAnimation on opacity {
                    id: opacityAnimSettings
                    to: 1.0
                    duration: 120
                    easing.type: Easing.OutQuad
                }
            }
        }
    }
}
