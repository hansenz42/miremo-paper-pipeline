# Miremo Paper Pipeline

一个面向英文论文的术语抽取工具，提供预选、文章与章节 Meta、逐分片细读和词表整理的完整命令行流程。输出包含术语名称、定义、原文位置和归并映射。以 [Attention Is All You Need](https://arxiv.org/abs/1706.03762) 为例。

配套文章：[从文档到知识图谱：用 Ontology 引导文档预处理](https://www.imassen.com/blog/2026-10-28-doc-ontology-keywords-draft/)。

处理范围固定为 **TERM（术语）**，无需提供 Ontology。

## 安装

Python 3.11。无需启动 Miremo、数据库或个人知识图谱。

```sh
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
```

固定依赖版本见 `requirements-lock.txt`，可用 `pip install -r requirements-lock.txt` 安装。英文模型从官方 GitHub Release 下载。

## 运行

先下载论文并执行本地预选（不调用大模型）：

```sh
python run.py --attention --output output/attention
```

也可提供自己的英文 Markdown、纯文本或 PDF：

```sh
python run.py --input paper.md --output output/my-paper
```

编辑 `config/model.json`：填写支持 Chat Completions、JSON object 输出的模型名称及服务地址。`request_options` 可设置服务商所需参数，例如 `{"extra_body":{"enable_thinking":false}}`，仅在所选服务支持时使用。API Key 从环境变量读取，不放进配置文件：

```sh
export PAPER_API_KEY='你的 API Key'
python run.py --attention --output output/attention --execute --max-calls 500
```

预选不绑定模型配置，可以先查看候选表再配置模型。首次 `--execute` 后，该输出目录绑定模型配置；输入、内置 TERM 规则、代码、依赖版本或已绑定的模型配置改变时须换目录。完整流程可能有数百次模型请求，消耗取决于词表大小和模型。`--max-calls` 限制该输出目录累计的请求尝试数，**不是金额或 token 上限**。服务商的账户预算应自行设置。

执行失败后，用相同参数重跑：已完成且请求哈希一致的模型返回会复用，失败的调用会重试。达到请求上限时，可提高 `--max-calls` 后继续。输入超过预算时明确报错或拆分独立候选，不静默截断候选表。

## 输出

| 文件 | 内容 |
| --- | --- |
| `input.txt` | 实际处理的文本快照 |
| `tables/shards.json`、`tables/chapters.json` | 章节、分片、原文位置与阅读顺序 |
| `rankings.json` | 全量 JATE 原始评分 |
| `tables/candidates.json` | 初始名称、评分、出现位置、关联分片和候选字段 |
| `document-meta.json` | 文章概述、文档作用、术语关注方向和来源 |
| `chapter-meta.json` | 各章概述、章节作用、关注方向与不确定性 |
| `reading/` | 细读批注、新术语候选、名称建议及模型调用记录 |
| `final-candidates.json` | 整理后的全部对象，包含 retain / exclude / pending 状态 |
| `candidate-mapping.json` | 原候选到规范名称的归并映射 |
| `summary.json` | 候选整理阶段统计；阅读阶段用量见 reading 调用回执 |
| `REPORT.md` | 人可读的结果入口与保留术语定义 |
| `refinement/` | 判断、身份比较、定义生成及逐条正文依据 |
| `manifest.json`、`model-config.json` | 输入和代码哈希、依赖及模型配置 |

最终词表保留排除和待确认项，便于追踪每个初始候选的去向。模型整理完成不代表事实已人工核验，也不等于写入知识图谱。

## 执行流程与算法

1. **输入适配**：PDF 使用 pypdf 提取文本；英文编号标题或 Markdown 标题识别章节。推荐检查 `input.txt` 与章节表，复杂公式、表格和多栏 PDF 的提取可能失真。
2. **分片**：采用结构优先切片，目标约 1000 字符、上限 1200 字符，保留原文偏移与阅读顺序。
3. **预选**：spaCy `en_core_web_sm` 分词和词性标注，JATE 3.3.0 C-Value 对全文的 1–5 词候选评分，最低频次 1；清理名称、名词词形去重，不做 Top-K 截断。
4. **原文定位**：使用名词词形匹配，记录出现分片及精确字符位置。
5. **粗读**：模型抽样生成文章和章节 Meta；Meta 是阅读辅助，不是事实证据。
6. **细读**：逐分片读取正文、Meta 与相关候选，累积语境理解、名称建议和新候选。
7. **整理**：先逐候选判断，再比较疑似同义对象，最后回到引用正文生成定义；保留归并映射和证据。

## 适用范围与限制

- 支持英文论文中的术语抽取，不处理其他实体类型、关系抽取或知识图谱写入。
- PDF 中的公式、表格、图片和多栏排版可能无法完整还原，建议先检查提取文本；也可直接提供整理后的 Markdown。
- 模型生成的定义和归并结果需要人工检查。输入文本、模型与处理版本不同，结果可能与配套文章中的示例不同。

## 测试

```sh
python -m unittest discover -s tests -v
```

测试使用模拟模型回答，覆盖数据流、证据约束、失败处理和续跑机制，无需 API Key。测试通过不代表真实模型的抽取质量。

## 许可证

代码使用 [MIT 许可证](LICENSE)。第三方依赖及模型遵循各自的许可证。论文由使用者从 arXiv 下载，其内容不属于本代码的 MIT 授权范围。
