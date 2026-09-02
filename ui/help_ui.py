"""面向安装包用户的应用使用帮助。"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon as FIF,
    IconWidget,
    ScrollArea,
    SegmentedWidget,
    StrongBodyLabel,
    TitleLabel,
)


class HelpUI(QFrame):
    """介绍首次使用流程、页面功能和常见问题。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("helpInterface")
        self._setup_ui()

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(32, 28, 32, 0)
        root_layout.setSpacing(18)

        title = TitleLabel("使用帮助")
        subtitle = BodyLabel("按照下面的步骤完成配置，并在正式接待客户前做好检查。")
        subtitle.setWordWrap(True)
        root_layout.addWidget(title)
        root_layout.addWidget(subtitle)

        self.pivot = SegmentedWidget(self)
        self.pivot.setFixedWidth(420)
        self.stacked_widget = QStackedWidget(self)

        pages = [
            ("quickStart", "快速开始", self._create_quick_start_page()),
            ("features", "功能说明", self._create_feature_page()),
            ("troubleshooting", "疑难解答", self._create_troubleshooting_page()),
        ]
        for index, (route_key, text, page) in enumerate(pages):
            self.stacked_widget.addWidget(page)
            self.pivot.addItem(
                routeKey=route_key,
                text=text,
                onClick=lambda checked=False, i=index: self.stacked_widget.setCurrentIndex(i),
            )

        self.pivot.setCurrentItem("quickStart")
        self.stacked_widget.setCurrentIndex(0)
        root_layout.addWidget(self.pivot, 0, Qt.AlignmentFlag.AlignLeft)
        root_layout.addWidget(self.stacked_widget, 1)

    def _create_quick_start_page(self) -> ScrollArea:
        steps = [
            (
                FIF.SETTING,
                "1. 配置 AI 模型",
                "打开“设置”，填写供应商名称、API Base URL、API Key 和模型名称。"
                "建议先“拉取模型”，再“测试连接”，确认成功后点击右上角“保存”。",
            ),
            (
                FIF.PEOPLE,
                "2. 分配并添加子账号",
                "建议准备两个不同的客服子账号：A 只登录本软件负责 AI 回复，B 只登录"
                "拼多多官方客户端负责人工接管。在“店铺运营”中使用账号密码添加子账号 A。",
            ),
            (
                FIF.DOCUMENT,
                "3. 准备知识库",
                "打开“知识库”并选择店铺。首次同步商品时建议使用“增量同步”；"
                "在“客服知识”中补充物流、售后、退款和发票等店铺规则。",
            ),
            (
                FIF.EDIT,
                "4. 设置转人工关键词",
                "在“关键词管理”中添加“转人工”“投诉”等明确词语。"
                "这些词用于触发人工接管，不是普通问答关键词。",
            ),
            (
                FIF.PLAY,
                "5. 启动自动回复",
                "打开“店铺运营”，点击“刷新”。先验证账号，状态变为在线后启动自动回复；"
                "多账号可勾选后使用“批量启动”。",
            ),
            (
                FIF.HISTORY,
                "6. 观察运行情况",
                "在“日志管理”中查看连接、收发消息和异常记录。需要暂停时点击"
                "“停止”或“批量停止”，确认停止后再进行账号或模型调整。",
            ),
        ]
        content = self._create_content_container()
        layout = content.layout()
        for icon, title, description in steps:
            layout.addWidget(self._create_info_card(icon, title, description))

        layout.addWidget(
            self._create_bullet_card(
                FIF.INFO,
                "正式启用前检查",
                [
                    "模型连接测试成功，且模型名称与供应商后台完全一致。",
                    "至少用一条测试会话检查语气、知识引用和转人工效果。",
                    "确认产品知识和客服规则属于当前店铺，避免跨店铺使用错误内容。",
                    "确认 AI 子账号 A 已上线，人工子账号 B 在拼多多客户端保持在线。",
                    "同一个客服账号不要同时登录本软件和拼多多官方客户端。",
                ],
            )
        )
        layout.addStretch()
        return self._wrap_scroll_area(content)

    def _create_feature_page(self) -> ScrollArea:
        content = self._create_content_container()
        layout = content.layout()
        sections = [
            (
                FIF.CHAT,
                "店铺运营",
                [
                    "“验证”刷新平台登录状态，“启动/停止”控制 AI 自动回复连接。",
                    "只有在线账号可以启动自动回复；批量启动只处理选中且符合条件的账号。",
                    "关闭应用时会尝试停止全部回复任务，但日常维护建议先手动停止。",
                ],
            ),
            (
                FIF.PEOPLE,
                "店铺与账号",
                [
                    "建议使用客服子账号的账号密码登录；保存密码后，账号异常时可以快速重新登录。",
                    "“验证”用于刷新登录凭证和账号状态；账号异常时先验证再重试。",
                    "同一店铺可以保存多个账号，应用会按店铺和账号隔离运行状态。",
                    "推荐 A/B 子账号分工：A 仅登录本软件，B 仅登录官方客户端。",
                    "同一账号多终端登录可能出现能接收消息但无法发送回复。",
                ],
            ),
            (
                FIF.DOCUMENT,
                "知识库",
                [
                    "产品知识来自店铺商品同步；增量同步只处理本地没有的商品。",
                    "客服知识支持逐条维护，也支持 Excel 批量导入。",
                    "批量导入前四列依次为一级分类、二级分类、话术标题、话术内容。",
                ],
            ),
            (
                FIF.EDIT,
                "关键词与人工接管",
                [
                    "关键词命中后会尝试把会话转给其他在线人工客服。",
                    "转人工受“设置”中的业务时间影响，且需要存在可接管的客服。",
                    "关键词支持批量粘贴，每行一个；避免使用含义过宽的单字或短词。",
                    "转接成功后，人工客服在拼多多官方客户端打开会话并继续回复。",
                    "处理完成后，人工客服可结束会话，或在官方客户端转回 AI 子账号。",
                    "存在多个人工账号时，当前版本会选择客服列表中的首个账号。",
                ],
            ),
            (
                FIF.SETTING,
                "设置",
                [
                    "可以保存多个 OpenAI 兼容供应商，列表中选中的供应商为当前使用项。",
                    "提示词决定回复规则和语气，修改后应先用测试会话验证。",
                    "业务时间主要用于人工转接判断和告知客户人工服务时间。",
                ],
            ),
        ]
        for icon, title, bullets in sections:
            layout.addWidget(self._create_bullet_card(icon, title, bullets))
        layout.addStretch()
        return self._wrap_scroll_area(content)

    def _create_troubleshooting_page(self) -> ScrollArea:
        content = self._create_content_container()
        layout = content.layout()
        layout.addWidget(
            self._create_bullet_card(
                FIF.INFO,
                "使用注意事项",
                [
                    "启动自动回复后会处理真实客户消息，首次使用应避开高峰并持续观察日志。",
                    "模型对话和商品知识提取会产生供应商费用，全量同步前先确认额度。",
                    "API Key、账号 Cookie 和本地数据均为敏感信息，不要截图、转发或上传。",
                    "过于宽泛的转人工关键词会拦截正常咨询，应从少量明确词语开始配置。",
                    "切换模型、修改账号或大批量同步前，先停止正在运行的自动回复。",
                    "不要让同一客服账号同时登录本软件和拼多多官方客户端。",
                    "转人工首次启用时应测试完整流程，并观察 AI 是否停止回复该会话。",
                ],
            )
        )

        questions = [
            (
                "模型测试连接失败",
                "检查 API Base URL 是否为完整的 HTTP(S) 地址，API Key 是否有效、"
                "模型名称是否准确，以及供应商额度和网络是否正常。可先“拉取模型”再选择。",
            ),
            (
                "账号密码登录失败",
                "确认使用的是拼多多客服子账号、密码正确且账号未被其他终端登录。"
                "验证成功后，应用会保存登录态，后续可以快速重新登录。",
            ),
            (
                "如何使用子账号避免登录冲突",
                "在同一店铺创建两个不同的客服子账号。子账号 A 使用账号密码登录本软件，"
                "子账号 B 只登录拼多多官方客户端。两者必须具有不同的用户身份，"
                "并分别保持在线；不要交换登录终端。",
            ),
            (
                "同时打开官方客户端后能收消息但不能自动回复",
                "这通常是同一账号多终端竞争造成的。先在官方客户端退出该账号，"
                "在“店铺运营”中停止回复并点击“验证”，成功后重新启动自动回复。"
                "依次执行“刷新”“验证”“启动”，最后发送测试消息确认。",
            ),
            (
                "无法点击开始回复或提示账号未上线",
                "先在“店铺运营”点击“刷新”，再验证对应账号。"
                "验证成功后，在同一账号行重新启动自动回复。",
            ),
            (
                "AI 回复不准确或没有引用店铺资料",
                "确认选择了正确店铺并完成产品知识同步，同时补充对应客服知识。"
                "检查知识内容是否启用，再调整提示词并通过测试会话验证。",
            ),
            (
                "转人工关键词没有生效",
                "确认关键词已保存、当前时间在业务时间内，并且还有其他在线人工客服可接管。"
                "只有文本消息包含关键词时才会触发转接。",
            ),
            (
                "转人工后由谁处理",
                "人工子账号需要提前登录拼多多官方客户端并保持在线。转接成功后，"
                "人工客服在客户端的会话列表或转接通知中打开客户会话，直接回复；"
                "处理完成后结束会话，或按需转回 AI 子账号。",
            ),
            (
                "人工客户端没有收到转接会话",
                "确认人工子账号与 AI 子账号属于同一店铺，并具备接待和会话转移权限。"
                "同时检查人工账号是否在线、当前是否在业务时间内，以及日志中是否出现"
                "“会话已成功转接”。多个人工账号在线时还需确认实际转接目标。",
            ),
            (
                "转人工后 AI 仍在回复",
                "当前版本依赖拼多多平台在转接后停止向 AI 子账号分配该会话。"
                "若仍出现重复回复，应立即在本软件停止该账号的自动回复，由人工继续处理，"
                "并保留日志和发生时间用于问题反馈。",
            ),
            (
                "商品知识同步很慢",
                "同步需要获取商品并调用模型提取知识，商品较多时耗时和费用都会增加。"
                "优先使用增量同步，不要关闭应用，并通过进度条和日志观察状态。",
            ),
            (
                "仍然无法解决",
                "先停止所有自动回复，保留错误发生时间和复现步骤，并在“日志管理”查看记录。"
                "可前往“关于”页面，通过项目地址或联系二维码反馈问题。",
            ),
        ]
        for question, answer in questions:
            layout.addWidget(self._create_question_card(question, answer))
        layout.addStretch()
        return self._wrap_scroll_area(content)

    @staticmethod
    def _create_content_container() -> QWidget:
        content = QWidget()
        content.setObjectName("helpContent")
        content.setStyleSheet("#helpContent { background: transparent; }")
        content.setMaximumWidth(980)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 18, 10, 32)
        layout.setSpacing(12)
        return content

    @staticmethod
    def _wrap_scroll_area(content: QWidget) -> ScrollArea:
        container = QWidget()
        container.setObjectName("helpScrollCanvas")
        container.setStyleSheet("#helpScrollCanvas { background: transparent; }")
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(content, 1)
        container_layout.addStretch()

        scroll_area = ScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("ScrollArea { border: none; background: transparent; }")
        scroll_area.setWidget(container)
        return scroll_area

    @staticmethod
    def _create_info_card(icon, title: str, description: str) -> CardWidget:
        card = CardWidget()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 18, 22, 18)
        layout.setSpacing(16)

        icon_widget = IconWidget()
        icon_widget.setIcon(icon)
        icon_widget.setFixedSize(26, 26)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)
        title_label = StrongBodyLabel(title)
        description_label = BodyLabel(description)
        description_label.setWordWrap(True)
        text_layout.addWidget(title_label)
        text_layout.addWidget(description_label)

        layout.addWidget(icon_widget, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text_layout, 1)
        return card

    @staticmethod
    def _create_bullet_card(icon, title: str, bullets: list[str]) -> CardWidget:
        card = CardWidget()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 18, 22, 18)
        layout.setSpacing(16)

        icon_widget = IconWidget()
        icon_widget.setIcon(icon)
        icon_widget.setFixedSize(26, 26)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(7)
        text_layout.addWidget(StrongBodyLabel(title))
        for bullet in bullets:
            label = BodyLabel(f"• {bullet}")
            label.setWordWrap(True)
            text_layout.addWidget(label)

        layout.addWidget(icon_widget, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text_layout, 1)
        return card

    @staticmethod
    def _create_question_card(question: str, answer: str) -> CardWidget:
        card = CardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 17, 22, 18)
        layout.setSpacing(6)
        layout.addWidget(StrongBodyLabel(question))
        answer_label = CaptionLabel(answer)
        answer_label.setWordWrap(True)
        layout.addWidget(answer_label)
        return card
