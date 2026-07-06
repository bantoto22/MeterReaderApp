import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "TouchMetrics.js" as TouchMetrics

ScrollView {
    id: root
    clip: true

    property int maxContentWidth: 420
    property int sidePadding: width <= 420 ? TouchMetrics.compactPageMargin : TouchMetrics.pageMargin
    property int topPadding: width <= 420 ? TouchMetrics.compactPageMargin : TouchMetrics.pageMargin
    property int bottomPadding: width <= 420 ? 28 : 36
    property int contentSpacing: width <= 420 ? TouchMetrics.compactSectionSpacing : TouchMetrics.sectionSpacing
    default property alias pageContent: contentColumn.data

    contentWidth: availableWidth

    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ScrollBar.vertical.policy: ScrollBar.AsNeeded

    Flickable.boundsBehavior: Flickable.StopAtBounds
    Flickable.flickableDirection: Flickable.VerticalFlick
    Flickable.maximumFlickVelocity: 2800
    Flickable.interactive: true

    contentItem: Item {
        width: root.availableWidth
        implicitHeight: contentColumn.implicitHeight + root.topPadding + root.bottomPadding

        ColumnLayout {
            id: contentColumn
            width: Math.min(parent.width - (root.sidePadding * 2), root.maxContentWidth)
            x: Math.max(root.sidePadding, (parent.width - width) / 2)
            y: root.topPadding
            spacing: root.contentSpacing
        }
    }
}
