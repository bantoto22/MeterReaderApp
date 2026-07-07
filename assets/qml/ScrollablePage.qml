import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "TouchMetrics.js" as TouchMetrics

Flickable {
    id: root
    clip: true

    property int maxContentWidth: 420
    property int pageSidePadding: width <= 420 ? TouchMetrics.compactPageMargin : TouchMetrics.pageMargin
    property int pageTopPadding: width <= 420 ? TouchMetrics.compactPageMargin : TouchMetrics.pageMargin
    property int pageBottomPadding: width <= 420 ? 28 : 36
    property int pageContentSpacing: width <= 420 ? TouchMetrics.compactSectionSpacing : TouchMetrics.sectionSpacing
    default property alias pageContent: contentColumn.data

    boundsBehavior: Flickable.StopAtBounds
    boundsMovement: Flickable.StopAtBounds
    flickableDirection: Flickable.VerticalFlick
    interactive: contentHeight > height
    synchronousDrag: true
    pressDelay: 120
    contentWidth: width
    contentHeight: contentContainer.implicitHeight

    ScrollBar.vertical: ScrollBar {
        policy: ScrollBar.AsNeeded
    }

    Item {
        id: contentContainer
        width: root.width
        implicitHeight: contentColumn.implicitHeight + root.pageTopPadding + root.pageBottomPadding

        ColumnLayout {
            id: contentColumn
            width: Math.min(contentContainer.width - (root.pageSidePadding * 2), root.maxContentWidth)
            x: Math.max(root.pageSidePadding, (contentContainer.width - width) / 2)
            y: root.pageTopPadding
            spacing: root.pageContentSpacing
        }
    }
}
