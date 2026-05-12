import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    color: "#f3f7fb"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 14

        Rectangle {
            Layout.fillWidth: true
            radius: 14
            color: "#0e4f8c"
            implicitHeight: 96

            Column {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 6

                Text {
                    text: "Zone Progress"
                    color: "white"
                    font.pixelSize: 24
                    font.bold: true
                }
                Text {
                    text: "QML summary panel for quick field review"
                    color: "#d8e9ff"
                    font.pixelSize: 14
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 14
            color: "white"
            border.color: "#dbe4ef"

            ScrollView {
                anchors.fill: parent
                anchors.margins: 16

                Text {
                    text: zoneBridge.zoneSummary
                    color: "#1f2d3d"
                    font.pixelSize: 18
                    wrapMode: Text.Wrap
                }
            }
        }
    }
}
