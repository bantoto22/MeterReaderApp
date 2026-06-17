import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: loginRoot
    width: parent ? parent.width : 480
    height: parent ? parent.height : 750

    // Premium Linear Gradient Background
    gradient: Gradient {
        GradientStop { position: 0.0; color: "#E8F0F8" }
        GradientStop { position: 1.0; color: "#F4F8FC" }
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 40, 380)
        spacing: 20

        // Logo Image with Entry Animation
        Image {
            id: logoImg
            Layout.alignment: Qt.AlignHCenter
            source: "../images/SLR logo 1.png"
            Layout.preferredWidth: 90
            Layout.preferredHeight: 90
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
                text: "San Lorenzo Ruiz Waterworks System"
                font.pixelSize: 18
                font.family: "Montserrat"
                font.bold: true
                color: "#0f172a"
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                Layout.maximumWidth: 340
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "Water Billing and Payment Record Management System"
                font.pixelSize: 11
                font.family: "Montserrat"
                color: "#475569"
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                Layout.maximumWidth: 340
            }
        }

        // Form Card (Glassmorphism white style)
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 300
            radius: 20
            color: "#FFFFFF"
            border.color: "#E2E8F0"
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: 14

                // Username field
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Text {
                        text: "👤 Username"
                        font.pixelSize: 11
                        font.family: "Montserrat"
                        font.bold: true
                        color: "#475569"
                    }

                    TextField {
                        id: txtUsername
                        Layout.fillWidth: true
                        placeholderText: "Enter your username"
                        font.pixelSize: 13
                        font.family: "Montserrat"
                        color: "#0f172a"
                        padding: 12
                        background: Rectangle {
                            radius: 10
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
                        text: "🔒 Password"
                        font.pixelSize: 11
                        font.family: "Montserrat"
                        font.bold: true
                        color: "#475569"
                    }

                    TextField {
                        id: txtPassword
                        Layout.fillWidth: true
                        placeholderText: "Enter your password"
                        echoMode: TextInput.Password
                        font.pixelSize: 13
                        font.family: "Montserrat"
                        color: "#0f172a"
                        padding: 12
                        background: Rectangle {
                            radius: 10
                            border.color: txtPassword.activeFocus ? "#3B82F6" : "#E2E8F0"
                            border.width: txtPassword.activeFocus ? 2 : 1
                            color: txtPassword.activeFocus ? "#FFFFFF" : "#F8FAFC"

                            Behavior on border.color { ColorAnimation { duration: 150 } }
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        onAccepted: loginButton.clicked()
                    }
                }

                // Error message (Null-safe check)
                Text {
                    id: txtError
                    Layout.fillWidth: true
                    text: (typeof loginBridge !== "undefined" && loginBridge) ? loginBridge.errorMessage : ""
                    color: "#EF4444"
                    font.pixelSize: 11
                    font.family: "Montserrat"
                    horizontalAlignment: Text.AlignHCenter
                    visible: text !== ""
                }

                // Login Button
                Button {
                    id: loginButton
                    Layout.fillWidth: true
                    implicitHeight: 44
                    scale: loginButton.pressed ? 0.96 : 1.0

                    Behavior on scale {
                        NumberAnimation { duration: 80 }
                    }

                    contentItem: Text {
                        text: "Log In"
                        color: "white"
                        font.pixelSize: 13
                        font.family: "Montserrat"
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        radius: 10
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: loginButton.pressed ? "#1E40AF" : (loginButton.hovered ? "#2563EB" : "#1D4ED8") }
                            GradientStop { position: 1.0; color: loginButton.pressed ? "#1E3A8A" : (loginButton.hovered ? "#1D4ED8" : "#1E40AF") }
                        }
                    }
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
            text: "© 2026 Municipality of San Lorenzo Ruiz"
            font.pixelSize: 10
            font.family: "Montserrat"
            color: "#64748b"
            Layout.topMargin: 8
        }
    }

    // Shake animation
    SequentialAnimation {
        id: shakeAnim
        loops: 1

        NumberAnimation { target: loginRoot; property: "x"; from: 0; to: -10; duration: 50; easing.type: Easing.InOutQuad }
        NumberAnimation { target: loginRoot; property: "x"; from: -10; to: 10; duration: 50; easing.type: Easing.InOutQuad }
        NumberAnimation { target: loginRoot; property: "x"; from: 10; to: -10; duration: 50; easing.type: Easing.InOutQuad }
        NumberAnimation { target: loginRoot; property: "x"; from: -10; to: 10; duration: 50; easing.type: Easing.InOutQuad }
        NumberAnimation { target: loginRoot; property: "x"; from: 10; to: -5; duration: 50; easing.type: Easing.InOutQuad }
        NumberAnimation { target: loginRoot; property: "x"; from: -5; to: 5; duration: 50; easing.type: Easing.InOutQuad }
        NumberAnimation { target: loginRoot; property: "x"; from: 5; to: 0; duration: 50; easing.type: Easing.InOutQuad }
    }

    Connections {
        target: (typeof loginBridge !== "undefined" && loginBridge) ? loginBridge : null
        function onLoginFailed() {
            shakeAnim.start()
        }
    }
}
