import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "TouchMetrics.js" as TouchMetrics

ScrollView {
    id: root
    clip: true

    property int maxContentWidth: 420
    property int pageSidePadding: width <= 420 ? TouchMetrics.compactPageMargin : TouchMetrics.pageMargin
    property int pageTopPadding: width <= 420 ? TouchMetrics.compactPageMargin : TouchMetrics.pageMargin
    property int pageBottomPadding: width <= 420 ? 28 : 36
    property int pageContentSpacing: width <= 420 ? TouchMetrics.compactSectionSpacing : TouchMetrics.sectionSpacing
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
        implicitHeight: contentColumn.implicitHeight + root.pageTopPadding + root.pageBottomPadding

        ColumnLayout {
            id: contentColumn
            width: Math.min(parent.width - (root.pageSidePadding * 2), root.maxContentWidth)
            x: Math.max(root.pageSidePadding, (parent.width - width) / 2)
            y: root.pageTopPadding
            spacing: root.pageContentSpacing
        }
    }
}
