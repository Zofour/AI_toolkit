"""测试注入器的 new_chat：点新对话并读取模型标签。"""
import chatbox_inject as I

inj = I.Injector("ws://127.0.0.1:1/ws", "x", 9333)
try:
    label = inj.new_chat()
    print("model label:", repr(label))
    print("active:", inj.active_session())
    print("input placeholder:", inj.conn().ev("(document.querySelector('textarea')||{}).placeholder||''")
          ["result"]["result"]["value"])
finally:
    inj.conn().close()
