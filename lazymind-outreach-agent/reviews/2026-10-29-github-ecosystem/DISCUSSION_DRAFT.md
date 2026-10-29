# Discussion draft — internal review only

Target: [alirezarezvani/claude-skills Discussions](https://github.com/alirezarezvani/claude-skills/discussions)

No Discussion, Issue or PR has been created.

## Title

Would a bounded LazyMind compatibility test be useful for one multi-stage skill?

## Body

Your repository now supports Codex and a broad set of research, finance, commercial, product, human-gate, and agent-harness skills. The contribution guide also asks people to check overlap and discuss uncertain ideas before building, so I am proposing a test plan here rather than opening a promotional issue or PR. Sources: https://github.com/alirezarezvani/claude-skills and https://github.com/alirezarezvani/claude-skills/blob/main/CONTRIBUTING.md.

Would it be useful to select one genuinely multi-stage skill—for example the RFP responder or one research-operations skill—and run a bounded compatibility comparison? The same public/synthetic input, model, tool permissions and skill commit would be used twice: once natively, and once after installing the Skill into a LazyMind workflow. We would compare only inspectable behavior: stage artifacts, explicit review questions, restart/resume after one injected failure, and whether unaffected stages remain unchanged. We would not claim that wrapping a Skill improves answer quality.

LazyMind is open source at https://github.com/LazyAGI/LazyMind. The only prior example we would use as a starting point is https://github.com/NicoYang1984/LazyMind/blob/fde2e68437caffa8dc6d706271dabc6073183938/examples/competitive-brief-skill2workflow/EVALUATION.md. That record includes negative results: autonomous execution stopped at 2/5, assisted recovery reached 5/5 at the session layer, and the originating external task still reported failure. It does not establish compatibility with this repository or reliable unattended execution.

I coordinate ecosystem compatibility outreach for LazyMind and am posting in that project capacity. There is no existing integration or endorsement. If maintainers are open to the question, the next step would be a one-page matrix for review before anyone runs code. Which single skill, if any, would make this experiment useful rather than duplicative?

