import QtQuick 2.15
import QtQuick.Shapes 1.15

Item {
    id: chatRoot
    objectName: "quickChatRoot"
    // 壁纸由 QWidget 父级统一绘制，Quick 只绘制消息和交互控件。

    signal historyRequested()
    signal bottomStateChanged(bool atBottom)
    signal linkActivated(string link)

    property string contentFamily: "Microsoft YaHei"
    property string metaFamily: "Segoe UI"
    property bool historyAvailable: true
    property bool historyPending: false
    property bool suppressHistory: true
    property int newMessageCount: 0
    property bool bottomStateKnown: false
    property bool lastAtBottom: true

    function isNearBottom() {
        return messageList.atYEnd || messageList.contentY >= messageList.contentHeight - messageList.height - 60
    }

    function updateBottomState(force) {
        var atBottom = chatRoot.isNearBottom()
        // contentY 每个滚动像素都会变化，但 Python 只需要知道状态
        // 跨过底部阈值的时刻，避免滚动过程中产生跨语言信号风暴。
        if (force || !chatRoot.bottomStateKnown || atBottom !== chatRoot.lastAtBottom) {
            chatRoot.bottomStateKnown = true
            chatRoot.lastAtBottom = atBottom
            chatRoot.bottomStateChanged(atBottom)
        }
    }

    function setFonts(content, meta) {
        contentFamily = content || "Microsoft YaHei"
        metaFamily = meta || "Segoe UI"
    }

    function setHistoryAvailable(available) {
        historyAvailable = available
        if (!available)
            historyPending = false
    }

    function finishHistoryLoad() {
        historyPending = false
    }

    function loadMessages() {
        newMessageCount = 0
        historyPending = false
        suppressHistory = true
        Qt.callLater(function() {
            // 模型刚重置时 delegate 还没有完成文本测量；等待两轮事件循环，
            // 才能根据最终 contentHeight 定位到最后一条，避免首帧大片空白。
            messageList.forceLayout()
            messageList.positionViewAtEnd()
            Qt.callLater(function() {
                messageList.forceLayout()
                messageList.positionViewAtEnd()
                suppressHistory = false
                updateBottomState(true)
            })
        })
    }

    function clearMessages() {
        newMessageCount = 0
        historyPending = false
        suppressHistory = true
        updateBottomState(true)
    }

    function notifyAppended(follow) {
        if (follow) {
            Qt.callLater(function() {
                messageList.positionViewAtEnd()
                newMessageCount = 0
                updateBottomState()
            })
        } else {
            newMessageCount += 1
        }
    }

    function jumpToLatest() {
        newMessageCount = 0
        messageList.positionViewAtEnd()
        updateBottomState(true)
    }

    property string prependAnchor: ""
    property real prependAnchorOffset: 0

    function preparePrepend(anchor) {
        prependAnchor = anchor
        var groupIndex = chatModel.groupIndexForMessage(anchor)
        var item = groupIndex >= 0 ? messageList.itemAtIndex(groupIndex) : null
        prependAnchorOffset = item ? item.y - messageList.contentY : 0
    }

    function restorePrepend() {
        Qt.callLater(function() {
            messageList.forceLayout()
            var groupIndex = chatModel.groupIndexForMessage(prependAnchor)
            if (groupIndex < 0)
                return
            messageList.positionViewAtIndex(groupIndex, ListView.Beginning)
            Qt.callLater(function() {
                var item = messageList.itemAtIndex(groupIndex)
                if (item)
                    messageList.contentY = item.y - prependAnchorOffset
                updateBottomState(true)
            })
        })
    }

    ListView {
        id: messageList
        objectName: "messageList"
        anchors.fill: parent
        clip: true
        model: chatModel
        spacing: 9
        topMargin: 8
        bottomMargin: 8
        // 只缓存视口附近少量分组，降低快速上滑时的 delegate 创建成本。
        cacheBuffer: 320
        reuseItems: true
        displayMarginBeginning: 0
        displayMarginEnd: 0
        pixelAligned: false
        maximumFlickVelocity: 3600
        flickDeceleration: 1800
        boundsBehavior: Flickable.StopAtBounds
        boundsMovement: Flickable.StopAtBounds
        delegate: Loader {
            id: listDelegate
            objectName: "chatDelegate"
            width: messageList.width
            height: item ? item.height : 0
            property string itemKind: kind
            property string itemDateText: dateText
            property var itemMessages: messages
            property real itemContentY: y
            property bool itemIsSelf: isSelf
            property string itemSenderName: senderName
            property string itemAvatarText: avatarText
            property string itemAvatarSource: avatarSource
            sourceComponent: kind === "date" ? dateDelegate : groupDelegate
        }

        onContentYChanged: {
            updateBottomState()
            if (!chatRoot.suppressHistory && chatRoot.historyAvailable && !chatRoot.historyPending
                    && contentY <= 20 && contentHeight > height + 20) {
                chatRoot.historyPending = true
                chatRoot.historyRequested()
            }
        }
        onContentHeightChanged: updateBottomState()
        onMovementEnded: updateBottomState()
    }

    Rectangle {
        id: newMessageButton
        visible: chatRoot.newMessageCount > 0
        z: 5
        width: 132
        height: 32
        radius: 8
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 16
        color: "#14171f"
        border.color: "#7a6538"
        border.width: 1

        Text {
            anchors.fill: parent
            text: "↓  " + (chatRoot.newMessageCount > 99 ? "99+" : chatRoot.newMessageCount) + "条新消息"
            color: "#FFD580"
            font.pixelSize: 12
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: chatRoot.jumpToLatest()
        }
    }

    Component {
        id: dateDelegate
        Item {
            width: parent ? parent.width : 0
            height: dateLabel.height + 16
            property string displayDate: parent ? parent.itemDateText : ""

            Rectangle {
                anchors.centerIn: parent
                width: dateLabel.width + 22
                height: dateLabel.height + 8
                radius: 14
                color: "#472f35"
                opacity: 0.82
            }
            Text {
                id: dateLabel
                anchors.centerIn: parent
                text: displayDate
                color: "#D0AAB3"
                font.family: chatRoot.contentFamily
                font.pixelSize: 12
            }
        }
    }

    Component {
        id: groupDelegate
        Item {
            id: group
            objectName: "messageGroup"
            width: parent ? parent.width : 0
            // 不能让短气泡把 36px 头像裁掉或压到下一组上。
            height: Math.max(avatarSize, stack.height)
            property bool outgoing: parent ? parent.itemIsSelf : false
            property real avatarSize: 36
            property string senderName: parent ? parent.itemSenderName : ""
            property string avatarText: parent ? parent.itemAvatarText : ""
            property string avatarSource: parent ? parent.itemAvatarSource : ""
            property var rows: parent ? (parent.itemMessages || []) : []
            property int rowCount: rows ? rows.length : 0
            // Loader 的 y 已经是 ListView contentItem 坐标，直接扣除 contentY
            // 得到视口位置，避免滚动中反复做 mapToItem 坐标映射。
            property real visibleGroupTop: parent ? parent.itemContentY - messageList.contentY : 0

            Item {
                id: avatarSlot
                width: 52
                height: group.height
                x: group.outgoing ? group.width - width : 0
                visible: true

                Rectangle {
                    id: avatarFrame
                    objectName: "groupAvatar"
                    width: group.avatarSize
                    height: group.avatarSize
                    x: (parent.width - width) / 2
                    radius: width / 2
                    color: "#394B63"
                    // 头像默认贴在组底；组靠近视口底部时随消息向上顶，
                    // 但永远不会越过本组顶部或落到下一组。
                    y: Math.max(0, Math.min(group.height - height,
                        messageList.height - height - 4 - group.visibleGroupTop))

                    Image {
                        id: avatarImage
                        anchors.fill: parent
                        source: group.avatarSource
                        fillMode: Image.PreserveAspectCrop
                        // Python 已在后台缓存 72px 圆形 PNG，QML 不再为每组
                        // 创建遮罩效果器，也不会让未加载的网络图泄漏成方形。
                        asynchronous: false
                        cache: true
                        visible: group.avatarSource !== ""
                    }
                    Text {
                        anchors.fill: parent
                        visible: group.avatarSource === ""
                        text: group.avatarText
                        color: "#FFFFFF"
                        font.family: chatRoot.contentFamily
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }

            Column {
                id: stack
                x: group.outgoing ? 0 : 52
                width: Math.max(1, group.width - 52)
                spacing: 2

                Text {
                    visible: !group.outgoing && group.senderName !== ""
                    text: group.senderName
                    height: visible ? 20 : 0
                    leftPadding: 10
                    color: "#6AC5E8"
                    font.family: chatRoot.contentFamily
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }

                Repeater {
                    id: messageRepeater
                    // A numeric model is reliable with arrays decoded from a Python role.
                    model: group.rowCount
                    delegate: Item {
                        id: bubbleRow
                        objectName: "bubbleRow"
                        width: stack.width
                        height: bubble.height
                        property var message: group.rows[index]
                        property bool outgoing: message ? message.isSelf : false
                        property real maxWidth: Math.min(480, Math.max(140, stack.width * 0.65))

                        Item {
                            id: bubble
                            width: message ? Math.min(maxWidth, Math.max(72,
                                15 + (message.tailSide === "left" ? 6 : 0) +
                                message.naturalWidth + (message.metaWidth > 0 ? 4 + message.metaWidth : 0))) : 72
                            height: Math.max(30, contentText.height + 9)
                            x: bubbleRow.outgoing ? bubbleRow.width - width -
                                (message && message.tailSide === "" ? 6 : 0) :
                                (message && message.tailSide === "left" ? 6 : 0)

                            property string pathData: message ? makePath(width, height, message.radii, message.tailSide) : ""

                            function cubic(r) { return r * 0.5522848 }
                            function makePath(w, h, radii, tail) {
                                var tl = Math.min(radii[0], Math.min(w, h) / 2)
                                var tr = Math.min(radii[1], Math.min(w, h) / 2)
                                var br = Math.min(radii[2], Math.min(w, h) / 2)
                                var bl = Math.min(radii[3], Math.min(w, h) / 2)
                                var k = 0.5522848
                                if (tail === "left") {
                                    var left = 6
                                    return "M " + (left + tl) + " 0 H " + (w - tr) +
                                        " C " + (w - tr + tr*k) + " 0 " + w + " " + (tr - tr*k) + " " + w + " " + tr +
                                        " V " + (h - br) + " C " + w + " " + (h - br + br*k) + " " + (w - br + br*k) + " " + h + " " + (w - br) + " " + h +
                                        " H " + (left + 8) + " C " + (left + 4) + " " + (h - 1) + " " + (left + 1) + " " + (h - 4) + " 0 " + h +
                                        " L " + left + " " + Math.max(tl, h - 7) + " V " + tl +
                                        " C " + left + " " + (tl - tl*k) + " " + (left + tl - tl*k) + " 0 " + (left + tl) + " 0 Z"
                                }
                                if (tail === "right") {
                                    var right = w - 6
                                    return "M " + tl + " 0 H " + (right - tr) +
                                        " C " + (right - tr + tr*k) + " 0 " + right + " " + (tr - tr*k) + " " + right + " " + tr +
                                        " V " + Math.max(tr, h - 7) +
                                        " C " + (right + 1) + " " + (h - 4) + " " + (right + 4) + " " + (h - 1) + " " + w + " " + h +
                                        " H " + (right - 8) + " L " + bl + " " + h +
                                        " C " + (bl - bl*k) + " " + h + " 0 " + (h - bl + bl*k) + " 0 " + (h - bl) +
                                        " V " + tl + " C 0 " + (tl - tl*k) + " " + (tl - tl*k) + " 0 " + tl + " 0 Z"
                                }
                                return "M " + tl + " 0 H " + (w - tr) +
                                    " C " + (w - tr + tr*k) + " 0 " + w + " " + (tr - tr*k) + " " + w + " " + tr +
                                    " V " + (h - br) + " C " + w + " " + (h - br + br*k) + " " + (w - br + br*k) + " " + h + " " + (w - br) + " " + h +
                                    " H " + bl + " C " + (bl - bl*k) + " " + h + " 0 " + (h - bl + bl*k) + " 0 " + (h - bl) +
                                    " V " + tl + " C 0 " + (tl - tl*k) + " " + (tl - tl*k) + " 0 " + tl + " 0 Z"
                            }

                            Shape {
                                anchors.fill: parent
                                ShapePath {
                                    fillColor: bubbleRow.outgoing ? "#8774E1" : "#212121"
                                    strokeWidth: 0
                                    strokeColor: "transparent"
                                    PathSvg { path: bubble.pathData }
                                }
                            }

                            TextEdit {
                                id: contentText
                                x: message && message.tailSide === "left" ? 14 : 8
                                y: 4
                                width: Math.max(1, bubble.width - x - 7 -
                                    (message && message.metaWidth > 0 ? message.metaWidth + 4 : 0))
                                height: Math.max(20, contentHeight)
                                text: message ? (message.hasLinks ? message.richContent : message.plainContent) : ""
                                textFormat: message && message.hasLinks ? TextEdit.RichText : TextEdit.PlainText
                                color: "#FFFFFF"
                                font.family: chatRoot.contentFamily
                                font.pixelSize: 16
                                wrapMode: TextEdit.Wrap
                                readOnly: true
                                selectByMouse: true
                                selectByKeyboard: true
                                persistentSelection: false
                                onLinkActivated: chatRoot.linkActivated(link)
                            }

                            Row {
                                anchors.right: parent.right
                                anchors.rightMargin: 7
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 3
                                spacing: 2

                                Text {
                                    visible: message && message.time !== ""
                                    text: message ? message.time : ""
                                    color: bubbleRow.outgoing ? "#B3A7EC" : "#A7A7A7"
                                    font.family: chatRoot.metaFamily
                                    font.pixelSize: 12
                                }
                                Text {
                                    visible: bubbleRow.outgoing && message && message.time !== ""
                                    text: "✓✓"
                                    color: "#F7F4FF"
                                    font.family: chatRoot.metaFamily
                                    font.pixelSize: 11
                                }
                            }
                        }
                    }
                }
            }
        }
    }

}
