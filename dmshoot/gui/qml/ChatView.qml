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
    // 滚轮只负责把输入交给 ListView 的原生 Flickable 物理。
    property real mouseWheelStep: 120
    property real wheelSensitivity: 18.0
    property real wheelMaxVelocity: 12000
    property real wheelImmediateFactor: 0.75
    property int wheelBurstLevel: 0
    property int wheelDirection: 0
    property real lastWheelTime: 0
    // 记录正在等待布局稳定的边界，避免 contentHeight 增长后停在旧边界。
    property int boundaryLock: 0 // 1 = top, -1 = bottom
    property int boundarySettleTicks: 0

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
            positionAtChatEnd()
            Qt.callLater(function() {
                messageList.forceLayout()
                positionAtChatEnd()
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
                positionAtChatEnd()
                newMessageCount = 0
                updateBottomState()
            })
        } else {
            newMessageCount += 1
        }
    }

    function jumpToLatest() {
        newMessageCount = 0
        positionAtChatEnd()
        updateBottomState(true)
    }

    function clampContentY(value) {
        var maximum = Math.max(0, messageList.contentHeight - messageList.height)
        return Math.max(0, Math.min(maximum, value))
    }

    function positionAtChatEnd() {
        messageList.forceLayout()
        if (messageList.count > 0)
            messageList.positionViewAtIndex(messageList.count - 1, ListView.End)
        else
            messageList.contentY = 0
    }

    function settleBoundary(lock) {
        boundaryLock = lock
        boundarySettleTicks = 0
        boundarySettleTimer.start()
        messageList.cancelFlick()
        if (lock > 0)
            messageList.positionViewAtBeginning()
        else
            positionAtChatEnd()
    }

    function scrollByWheel(delta, animate) {
        if (Math.abs(delta) < 0.1)
            return

        if (!animate) {
            wheelBurstLevel = 0
            wheelDirection = 0
            lastWheelTime = 0
            boundaryLock = 0
            boundarySettleTimer.stop()
            messageList.cancelFlick()
            var directY = clampContentY(messageList.contentY - delta)
            messageList.contentY = directY
            var directMaximum = Math.max(0, messageList.contentHeight - messageList.height)
            if (directY <= 0 && delta > 0)
                settleBoundary(1)
            else if (directY >= directMaximum && delta < 0)
                settleBoundary(-1)
            return
        }

        var now = Date.now()
        var direction = delta > 0 ? 1 : -1
        if (wheelDirection === direction && now - lastWheelTime < 220) {
            wheelBurstLevel = Math.min(8, wheelBurstLevel + 1)
        } else {
            wheelBurstLevel = 1
        }
        wheelDirection = direction
        lastWheelTime = now

        // 第一帧立即移动，消除“滚了但页面还不动”的迟滞。
        var immediate = delta * wheelImmediateFactor
        var nextY = clampContentY(messageList.contentY - immediate)
        boundaryLock = 0
        boundarySettleTimer.stop()
        messageList.contentY = nextY

        // 当前速度由 Flickable 自己维护。连续同向输入叠加原生速度，
        // 反向输入先取消旧 flick，避免边界附近或反向时出现回弹。
        var burstMultiplier = 1.0 + Math.min(7, wheelBurstLevel - 1) * 0.28
        var impulse = delta * wheelSensitivity * burstMultiplier
        // Qt 的 verticalVelocity 表示内容本身的运动方向，
        // flick() 参数表示视图滚动方向，二者符号相反。
        var currentVelocity = -messageList.verticalVelocity
        if (currentVelocity * impulse < 0) {
            messageList.cancelFlick()
            currentVelocity = 0
        }
        var velocity = Math.max(
            -wheelMaxVelocity,
            Math.min(wheelMaxVelocity, currentVelocity + impulse)
        )
        var maximum = Math.max(0, messageList.contentHeight - messageList.height)
        if ((nextY <= 0 && velocity > 0) || (nextY >= maximum && velocity < 0)) {
            settleBoundary(nextY <= 0 ? 1 : -1)
            return
        }
        messageList.flick(0, velocity)
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
        // 给最后一条消息留出完整滚动空间，避免被底部输入/状态区域裁掉。
        bottomMargin: 72
        // 只缓存视口附近少量分组，降低快速上滑时的 delegate 创建成本。
        cacheBuffer: 320
        reuseItems: true
        displayMarginBeginning: 0
        displayMarginEnd: 0
        pixelAligned: false
        maximumFlickVelocity: 12000
        flickDeceleration: 900
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
            // 即使来自内部 Flickable/拖动路径，也不允许越过边界。
            var maximum = Math.max(0, contentHeight - height)
            if (contentY < 0 || contentY > maximum) {
                cancelFlick()
                contentY = Math.max(0, Math.min(maximum, contentY))
                return
            }
            if (chatRoot.boundaryLock !== 0) {
                var atLockedBoundary = chatRoot.boundaryLock > 0 ? atYBeginning : atYEnd
                if (!atLockedBoundary) {
                    cancelFlick()
                    if (chatRoot.boundaryLock > 0)
                        positionViewAtBeginning()
                    else
                        positionViewAtEnd()
                    return
                }
            }
            updateBottomState()
            if (!chatRoot.suppressHistory && chatRoot.historyAvailable && !chatRoot.historyPending
                    && contentY <= 20 && contentHeight > height + 20) {
                chatRoot.historyPending = true
                chatRoot.historyRequested()
            }
        }
        onContentHeightChanged: {
            updateBottomState()
            if (chatRoot.boundaryLock !== 0) {
                cancelFlick()
                if (chatRoot.boundaryLock > 0)
                    positionViewAtBeginning()
                else
                    positionViewAtEnd()
            }
        }
        onMovementEnded: updateBottomState()
    }

    // 只处理 delegate 异步测量造成的边界变化，不驱动普通滚动。
    Timer {
        id: boundarySettleTimer
        objectName: "boundarySettleTimer"
        interval: 16
        repeat: true
        onTriggered: {
            if (chatRoot.boundaryLock === 0) {
                stop()
                return
            }
            messageList.forceLayout()
            messageList.cancelFlick()
            if (chatRoot.boundaryLock > 0)
                messageList.positionViewAtBeginning()
            else
                positionAtChatEnd()
            boundarySettleTicks += 1
            if (boundarySettleTicks >= 32)
                stop()
        }
    }

    WheelHandler {
        id: wheelHandler
        objectName: "chatWheelHandler"
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        target: null
        onWheel: (event) => {
            // 普通鼠标通常同时带 angleDelta 和 pixelDelta，优先使用
            // angleDelta，避免高分辨率鼠标被当成几像素的小滚动。
            var angle = event.angleDelta.y
            var delta = angle ? angle / 120 * chatRoot.mouseWheelStep : event.pixelDelta.y
            var animate = Boolean(angle)
            chatRoot.scrollByWheel(delta, animate)
            event.accepted = true
        }
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
            height: Math.max(avatarSize, stack.height + 2)
            property bool outgoing: parent ? parent.itemIsSelf : false
            property real avatarSize: 36
            property string senderName: parent ? parent.itemSenderName : ""
             property string avatarText: parent ? parent.itemAvatarText : ""
             property string avatarSource: parent ? parent.itemAvatarSource : ""
             property var rows: parent ? (parent.itemMessages || []) : []
             property int rowCount: rows ? rows.length : 0
             property real messageStackBottom: stack.y + stack.height
            // Loader 的 y 已经是 ListView contentItem 坐标，直接扣除 contentY
            // 得到视口位置，避免滚动中反复做 mapToItem 坐标映射。
             // 使用 delegate 在滚动内容中的真实位置。itemContentY 由 Loader
             // 提供，但保留 contentY 依赖，确保滚动时头像实时重新定位。
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
                    // 正常状态贴在本组最后一条消息底部；只有组底超出
                    // 视口底部时才向上顶，不允许头像漂到别的消息组。
                    y: Math.max(0, Math.min(group.messageStackBottom - height,
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
                height: childrenRect.height

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
                        // The row owns the complete vertical footprint. This keeps
                        // Column from placing the next bubble before TextEdit has
                        // finished measuring a wrapped message.
                        height: topGap + Math.max(30, bubble.height,
                            contentText.contentHeight + 11) + 2
                        property var message: group.rows[index]
                        property bool outgoing: message ? message.isSelf : false
                        property real maxWidth: Math.min(480, Math.max(140, stack.width * 0.65))
                        property real topGap: message ? (message.gapBefore || 0) : 0

                        Item {
                            id: bubble
                            objectName: "bubbleSurface"
                            width: message ? Math.min(maxWidth, Math.max(72,
                                15 + (message.tailSide === "left" ? 6 : 0) +
                                message.naturalWidth + (message.metaWidth > 0 ? 4 + message.metaWidth : 0))) : 72
                            // 文本高度是气泡的唯一垂直来源；元信息只占右下角，
                            // 不能再让复用中的旧 Loader 高度参与计算。
                            height: Math.max(30, contentText.height + 11)
                            y: bubbleRow.topGap
                            x: bubbleRow.outgoing ? bubbleRow.width - width -
                                (message && message.tailSide === "" ? 6 : 0) :
                                (message && message.tailSide === "left" ? 0 : 6)
                            property real bodyLeft: x + (message && message.tailSide === "left" ? 6 : 0)

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
                                objectName: "bubbleText"
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
                                wrapMode: TextEdit.WrapAtWordBoundaryOrAnywhere
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
