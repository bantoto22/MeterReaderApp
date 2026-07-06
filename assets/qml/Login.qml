import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects

Rectangle {
    id: loginRoot
    width: parent ? parent.width : 480
    height: parent ? parent.height : 800
    clip: true

    property bool compactScreen: width <= 420
    property bool narrowScreen: width < 600
    property int horizontalPadding: compactScreen ? 22 : (narrowScreen ? 16 : 24)
    property int verticalPadding: compactScreen ? 16 : (narrowScreen ? 20 : 28)

    color: "#F4F7FB"

    Flickable {
        id: loginScroller
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: contentWrapper.height
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height

        Item {
            id: contentWrapper
            width: loginScroller.width
            height: loginColumn.implicitHeight + (loginRoot.verticalPadding * 2)

            ColumnLayout {
                id: loginColumn
                width: Math.min(
                    contentWrapper.width - (loginRoot.horizontalPadding * 2),
                    loginRoot.compactScreen ? 320 : (loginRoot.narrowScreen ? contentWrapper.width - (loginRoot.horizontalPadding * 2) : 420)
                )
                x: Math.max(loginRoot.horizontalPadding, (contentWrapper.width - width) / 2)
                y: loginRoot.verticalPadding
                spacing: loginRoot.compactScreen ? 14 : (loginRoot.narrowScreen ? 16 : 20)
                transform: Translate { id: shakeOffset }

                // Logo Image with Entry Animation
                Image {
                    id: logoImg
                    Layout.alignment: Qt.AlignHCenter
                    source: "../images/SLR logo 1.png"
                    Layout.preferredWidth: loginRoot.compactScreen ? 64 : (loginRoot.narrowScreen ? 72 : 80)
                    Layout.preferredHeight: loginRoot.compactScreen ? 64 : (loginRoot.narrowScreen ? 72 : 80)
                    fillMode: Image.PreserveAspectFit

                    // Soft entry scale and opacity animation
                    scale: 0.5
                    opacity: 0.0
                    Component.onCompleted: {
                        logoScaleAnim.start()
                        logoOpacityAnim.start()
                    }
                    NumberAnimation on scale {
                        id: logoScaleAnim
                        to: 1.0
                        duration: 600
                        easing.type: Easing.OutBack
                        running: false
                    }
                    NumberAnimation on opacity {
                        id: logoOpacityAnim
                        to: 1.0
                        duration: 600
                        easing.type: Easing.OutCubic
                        running: false
                    }
                }

                // Header
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Layout.alignment: Qt.AlignHCenter

                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.fillWidth: true
                        text: "San Lorenzo Ruiz Waterworks System"
                        font.pixelSize: loginRoot.compactScreen ? 15 : (loginRoot.narrowScreen ? 17 : 18)
                        font.family: "Montserrat"
                        font.bold: true
                        color: "#0f172a"
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                    }

                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.fillWidth: true
                        text: "Water Billing and Payment Record Management System"
                        font.pixelSize: loginRoot.compactScreen ? 9 : (loginRoot.narrowScreen ? 10 : 11)
                        font.family: "Montserrat"
                        color: "#475569"
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                    }
                }

                // Form Card
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: formLayout.implicitHeight + (formCardPadding * 2)
                    radius: 8
                    color: "#FFFFFF"
                    border.color: "#E2E8F0"
                    border.width: 1

                    layer.enabled: true
                    layer.effect: MultiEffect {
                        shadowEnabled: true
                        shadowBlur: 0.8
                        shadowHorizontalOffset: 0
                        shadowVerticalOffset: 4
                        shadowColor: "#15000000"
                    }

                    property int formCardPadding: loginRoot.compactScreen ? 14 : (loginRoot.narrowScreen ? 16 : 24)

                    ColumnLayout {
                        id: formLayout
                        anchors.fill: parent
                        anchors.margins: parent.formCardPadding
                        spacing: loginRoot.compactScreen ? 12 : 14

                        // Username field
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            Text {
                                text: "Username"
                                font.pixelSize: 11
                                font.family: "Montserrat"
                                font.bold: true
                                color: "#475569"
                            }

                            TextField {
                                id: txtUsername
                                Layout.fillWidth: true
                                implicitHeight: loginRoot.compactScreen ? 40 : 44
                                placeholderText: "Enter your username"
                                font.pixelSize: 13
                                font.family: "Montserrat"
                                color: "#0f172a"
                                padding: 12
                                background: Rectangle {
                                    radius: 8
                                    border.color: txtUsername.activeFocus ? "#3B82F6" : "#E2E8F0"
                                    border.width: txtUsername.activeFocus ? 2 : 1
                                    color: txtUsername.activeFocus ? "#FFFFFF" : "#F8FAFC"

                                    Behavior on border.color { ColorAnimation { duration: 150 } }
                                    Behavior on color { ColorAnimation { duration: 150 } }
                                }
                            }
                        }

                        // Password field
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            Text {
                                text: "Password"
                                font.pixelSize: 11
                                font.family: "Montserrat"
                                font.bold: true
                                color: "#475569"
                            }

                            TextField {
                                id: txtPassword
                                Layout.fillWidth: true
                                implicitHeight: loginRoot.compactScreen ? 40 : 44
                                placeholderText: "Enter your password"
                                echoMode: TextInput.Password
                                font.pixelSize: 13
                                font.family: "Montserrat"
                                color: "#0f172a"
                                padding: 12
                                background: Rectangle {
                                    radius: 8
                                    border.color: txtPassword.activeFocus ? "#3B82F6" : "#E2E8F0"
                                    border.width: txtPassword.activeFocus ? 2 : 1
                                    color: txtPassword.activeFocus ? "#FFFFFF" : "#F8FAFC"

                                    Behavior on border.color { ColorAnimation { duration: 150 } }
                                    Behavior on color { ColorAnimation { duration: 150 } }
                                }
                                onAccepted: loginButton.clicked()
                            }
                        }

                        // Error message
                        Text {
                            id: txtError
                            Layout.fillWidth: true
                            text: (typeof loginBridge !== "undefined" && loginBridge) ? loginBridge.errorMessage : ""
                            color: "#EF4444"
                            font.pixelSize: 11
                            font.family: "Montserrat"
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                            visible: text !== ""
                        }

                        // Login Button
                        Button {
                            id: loginButton
                            Layout.alignment: Qt.AlignHCenter
                            Layout.preferredWidth: loginRoot.compactScreen ? Math.min(parent.width, 220) : parent.width
                            implicitHeight: loginRoot.compactScreen ? 40 : 44
                            scale: loginButton.pressed ? 0.96 : 1.0

                            Behavior on scale {
                                NumberAnimation { duration: 80 }
                            }

                            contentItem: Text {
                                text: "Log In"
                                color: "white"
                                font.pixelSize: loginRoot.compactScreen ? 12 : 13
                                font.family: "Montserrat"
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Rectangle { radius: 8; color: loginButton.pressed ? "#1E40AF" : (loginButton.hovered ? "#1D4ED8" : "#2563EB") }
                            onClicked: {
                                if (typeof loginBridge !== "undefined" && loginBridge) {
                                    loginBridge.attemptLogin(txtUsername.text, txtPassword.text)
                                }
                            }
                        }
                    }
                }

                // Footer Copyright
                Text {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.fillWidth: true
                    text: "Copyright 2026 Municipality of San Lorenzo Ruiz"
                    font.pixelSize: 10
                    font.family: "Montserrat"
                    color: "#64748b"
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    Layout.topMargin: 4
                }
            }
        }
    }

    // Shake animation
    SequentialAnimation {
        id: shakeAnim
        loops: 1

        NumberAnimation { target: shakeOffset; property: "x"; from: 0; to: -10; duration: 50; easing.type: Easing.InOutQuad }
        NumberAnimation { target: shakeOffset; property: "x"; from: -10; to: 10; duration: 50; easing.type: Easing.InOutQuad }
        NumberAnimation { target: shakeOffset; property: "x"; from: 10; to: -10; duration: 50; easing.type: Easing.InOutQuad }
        NumberAnimation { target: shakeOffset; property: "x"; from: -10; to: 10; duration: 50; easing.type: Easing.InOutQuad }
        NumberAnimation { target: shakeOffset; property: "x"; from: 10; to: -5; duration: 50; easing.type: Easing.InOutQuad }
        NumberAnimation { target: shakeOffset; property: "x"; from: -5; to: 5; duration: 50; easing.type: Easing.InOutQuad }
        NumberAnimation { target: shakeOffset; property: "x"; from: 5; to: 0; duration: 50; easing.type: Easing.InOutQuad }
    }

    Connections {
        target: (typeof loginBridge !== "undefined" && loginBridge) ? loginBridge : null
        function onLoginFailed() {
            shakeAnim.start()
        }
    }
}
