# 拒收附件

`README.md` 说明原有的冻结、发行、实收和报告领取流程。次班使用新增附件复核不可达结论，核对范围是报告指定的那次实收和收件窗。

## 值班入口

- `adjudicate.verdict.check_with_rejection(conn, report_id, request, *, before_commit=None)` 接收与 `check` 相同的报告号及 `DeliveryRequest`，返回 `ReportView`。可达时沿用原裁决，不附拒收附件。不可达时将附件与报告、首执一并签存。回调在本次资料写入后、事务提交前调用，异常原样传出且整次签存回滚。其余输入、报告号冲突和初始化规则沿用原接口。
- `reports.history.read_rejection(conn, report_id)` 返回签发时的原附件 `bytes`。旧报告和可达报告返回 `None`，未知报告号抛 `KeyError`。断源并重开工作区后仍可按原号领取。报告声明有附件但附件缺失或与快照绑定不符时抛 `ValueError`。
- `adjudicate.verdict.verify_rejection(report, received, attachment)` 是无需数据库连接的复核入口。`report` 是 `ReportView`，`received` 是 `accept` 或 `load_received` 返回的 `ReceivedPackage`，`attachment` 是附件字节。证据有效时返回 `True`。错件、漏证、无效格式或绑定均抛 `ValueError`。可达报告和没有附件的旧报告不能作为有效拒收证据使用。

## 复核口径

复核以报告内的指定请求和经实收核验的固定件为依据。按站声明的时间集由有限个闭区间表示，可以为空。逐项核对该声明是否覆盖全部应纳入的时刻，并能排除合法送达。允许保守覆盖，覆盖与排除必须同时成立。传输、具名保管任次、精确时间及至少一次传输的规则沿用 `README.md`。复核要检查附件实际声明的集合，可以复用时间运算，不能用重跑签发核定或比对摘要代替这些检查。

附件的编码和时间声明的含义由实现确定，交付时说明如何读出声明及核对绑定。首执通过报告快照约束请求和原附件字节。复核须核对报告指定的实收号、冻结身份、发行号和固定件摘要。原 `check`、`read_report` 和旧首执继续可用。

## 附件编码与绑定（交付说明）

附件是规范化 JSON 字节（`sort_keys=True`、紧凑分隔符、ASCII），字段固定为：

- `version`：固定为 `1`；
- `report_id`、`receipt_id`：报告号和报告指定的实收号；
- `survey_id`、`block_id`、`revision_id`：冻结身份；
- `release_id`、`package_digest`：发行号和固定件（实收实际字节）的 SHA-256 摘要；
- `station_sets`：按站给出的闭时间集，对象键为站名，值为闭区间数组；每个区间是 `[起, 止]` 两个最简有理秒字符串（如 `["1/3", "2"]`），空数组表示该站不存在任何实际在站时刻。

读出声明：`adjudicate.attachment.decode_rejection_attachment(bytes)` 校验格式并返回字典，`station_sets` 的值已还原为 `records.times.ClosedWindow` 元组。时间集由 `adjudicate.coverage.enumerate_station_sets(package, request)` 只凭固定件证据逐跳算出：源站取首跳出发闭窗的并；中继每段把到达窗与具名保管闭窗求交，再与出发闭窗求交并按固定正耗时平移，实际到达与续发必须同属一个具名任次且到达不晚于续发；区间在相触或重叠处合并，全部使用 `Fraction` 精确计入闭端点。

绑定链：报告快照新增可空字段 `attachment_digest`，值为附件原字节的 SHA-256（可达报告与旧报告为 `null`）。首执摘要的是整份报告快照，因此首执经快照同时约束请求和原附件字节；附件另存于工作区库的 `rejections` 表并带外键回指报告。`reports.history.read_rejection` 重开后按原报告号领回同一字节，并校验表内摘要与快照绑定一致，缺失或不符抛 `ValueError`。

`adjudicate.rejection_review.verify_rejection`（由 `adjudicate.verdict` 同名转出）无需数据库：先核报告为不可达且声明有附件、附件摘要等于快照绑定、七项身份字段与报告及指定实收逐一相符；再从实收件自带证据重算每站精确时间集，逐区间核对附件声明覆盖全部精确时刻（覆盖），且目的站声明与收件窗无任何公共点（排除）；最后确认至少存在一条传输。错件、漏证、非法格式、绑定不符、覆盖缺口或排除失败一律抛 `ValueError`，有效才返回 `True`。


## 交班样例

`samples/rejection.json` 是一份登记和基于同一实收件的两种收件窗。`cases` 中的 `expected` 沿用 `demo.py` 的原裁决格式。`early` 在 3 秒发出、4 秒到达。`late` 在 5 秒发出、6 秒到达。没有可在 5 秒实际到站的机会。

对 `[5,5]` 签存拒收，移除源库并重开工作区后，领回原报告、首执和同一附件，凭原实收件验真。对 `[6,6]` 核定时闭端点有效，应由 `late` 送达，报告无拒收附件。原 `gap` 和 `later` 样例继续用于核对具名保管任次。

使用 `.pointwise-runtime.json` 中现有的 `verify` 和 `demo` 入口。保留原回归和演示，补上拒收核验与按原号领取的演示，并核对错件、漏证及签存失败。
