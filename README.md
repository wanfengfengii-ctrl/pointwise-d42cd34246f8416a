# 试验录制交接档案

台架耐久试验站的资料室在白班固定交接依据，夜班只凭实际领到的固定件判断补录原块能否进窗，次班按报告号核账。Python 3.11 标准库和 SQLite 即可运行。

```sh
python3 -B check_project.py
python3 -B demo.py
```

`check_project.py` 是平台物化时提供的完整回归入口。演示逐份读取 `samples/` 的三种值班输入，登记、冻结、发行、实收并移除本次临时源库，再在离线工作区签发。演示重开离线库按原号读取首执和报告，并将手算预期与实际结果逐项比较。

## 值班接口

1. 白班用 `sqlite3.connect(path)` 打开源台账，调用 `records.revisions.initialize_revisions`、`records.surveys.initialize_surveys`、`issue.releases.initialize_releases`。`BlockRevision.from_document(document)` 读取班次登记，`save_revision(conn, revision)` 以原块号和修订号固定原始登记。同号同内容可重投，内容更正使用新修订号。
2. `records.surveys.freeze(conn, survey_id, block_id, revision_id)` 校验指定登记并返回 `FrozenSurvey`。通过其 `survey_id` 引用冻结快照。相同冻结绑定可重投。
3. `issue.releases.issue_package(conn, survey_id, release_id)` 返回 `IssuedPackage`。交班使用其中 `payload` 字节和清单身份。同发行号同调查单返回原字节及发行回执。
4. 夜班用 `receive.workspace.open_workspace(path)` 打开独立库，调用 `initialize_holdings` 和 `reports.signing.initialize_reports`。以交班任务指定的 `SurveyRef(survey_id, block_id, revision_id)` 调用 `receive.holdings.accept(conn, receipt_id, payload, expected)`，登记后得到 `ReceivedPackage`。指定实收号可用 `load_received` 读取。相同实收号、原字节及冻结绑定可重投。
5. `adjudicate.verdict.check(conn, report_id, DeliveryRequest(receipt_id, survey, source, destination, receipt_window))` 核定、签存并返回 `ReportView`。`receipt_window` 使用 `records.times.ClosedWindow`。新核定使用新报告号。`before_commit` 可选回调在写入报告和首执后、提交前执行，回调抛出的异常使本次写入回滚。
6. `reports.history.read_report(conn, report_id)` 领取固定 `ReportView`。`arrival` 和 `witness` 对不可达结论均为 `None`。首执绑定报告号及签发快照摘要。重开或重复初始化后继续按原号领取。
7. `adjudicate.verdict.check_with_rejection(conn, report_id, request, *, before_commit=None)` 与 `check` 同参；可达时沿用原裁决且不附拒收附件，不可达时把按站闭时间集附件与报告、首执在同一事务签存，回调失败三者一并回滚。`reports.history.read_rejection(conn, report_id)` 按原号领回签发时的原附件字节，旧报告和可达报告返回 `None`，未知报告号抛 `KeyError`，声明有附件但缺失或绑定不符抛 `ValueError`。`adjudicate.verdict.verify_rejection(report, received, attachment)` 是无连接复核入口，按 `REJECTION.md` 逐项核对覆盖与排除，错件、漏证、无效格式或绑定抛 `ValueError`，有效返回 `True`。

写入入口各自拥有事务，调用时连接应处于事务外。初始化可重复执行。未知标识抛出 `KeyError`，非法字段或身份冲突抛出 `ValueError`，SQLite 失败沿调用栈返回。发行、实收、报告号均在各自库内唯一。接收前由调用方从交班任务取得期望冻结身份。V1 外层摘要校验规范化的 JSON 内容，实收仍保存实际收到的字节。拒收附件的编码、按站闭时间集语义和绑定链见 `REJECTION.md`。

## 班次登记与核账口径

`revision` 登记含 `block_id`、`revision_id`、`stations`、`transmissions`、`custody_turns`。传输记录含 `id`、`source`、`target`、`opens`、`closes`、`duration`、`origin`。保管记录含 `id`、`station`、`opens`、`closes`、`origin`。`origin` 是原登记位置文本。时间可用 JSON 整数或精确十进制、有理数字符串，例如 `1/3`。Python 时间窗也可直接接收 `Fraction`。签报按最简有理数字符串编码。

冻结前检查必填时间、引用和网络。每次传输在自己的闭出发窗内选时刻，按固定正耗时到站。在中继，同一具名闭保管任次必须同时包含这份载荷的实际到达及下一跳发出。闭任次相触或重叠时仍独立判断。目的站按实际到达时间进窗。核定要求至少一次实际传输，起讫站相同在无环网络中得不到这类链。见证的每段记录传输窗、固定耗时、实际出发与到达及原出处。出站段的 `custody` 记录该段发出前用过的保管任次和原出处。等时的多条合法见证可任选一条。

样例分别覆盖单任次闭端点、掉电后再次送达，以及只有掉电前到达时的不可达。回归还核对分数时刻、宽出发窗、相邻交接共享的传输取值、错误实收、晚到更正及签发失败。
