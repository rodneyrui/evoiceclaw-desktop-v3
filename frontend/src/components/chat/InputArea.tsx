import { ArrowUp, Paperclip, Square } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const DRAFT_KEY = "evoiceclaw-v3-input-draft";

interface InputAreaProps {
  onSend: (message: string) => void;
  onStop?: () => void;
  isStreaming?: boolean;
  disabled?: boolean;
  placeholder?: string;
  inputRef?: React.RefObject<HTMLTextAreaElement | null>;
}

export function InputArea({
  onSend,
  onStop,
  isStreaming,
  disabled,
  placeholder,
  inputRef,
}: InputAreaProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState(
    () => sessionStorage.getItem(DRAFT_KEY) || "",
  );
  const fallbackRef = useRef<HTMLTextAreaElement>(null);
  const textareaRef = inputRef || fallbackRef;
  const isComposingRef = useRef(false);

  // 文字变化时持久化到 sessionStorage
  const updateValue = useCallback((text: string) => {
    setValue(text);
    if (text) {
      sessionStorage.setItem(DRAFT_KEY, text);
    } else {
      sessionStorage.removeItem(DRAFT_KEY);
    }
  }, []);

  const handleSend = useCallback(() => {
    if (value.trim()) {
      onSend(value.trim());
      updateValue("");
    }
  }, [value, onSend, updateValue]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey && !isComposingRef.current) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="p-6 bg-background/80 backdrop-blur-md border-t border-border relative z-20">
      <div className="max-w-4xl mx-auto relative flex items-end gap-2 bg-card border border-border rounded-xl p-2 focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/20 transition-all shadow-sm">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => updateValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onCompositionStart={() => {
            isComposingRef.current = true;
          }}
          onCompositionEnd={() => {
            isComposingRef.current = false;
          }}
          placeholder={placeholder || t("chat.inputPlaceholder")}
          disabled={disabled}
          className="flex-1 bg-transparent border-none text-sm resize-none max-h-32 min-h-[44px] p-3 focus:ring-0 focus:outline-none placeholder:text-muted-foreground/50 disabled:opacity-50 text-foreground"
          rows={1}
        />

        <div className="flex items-center gap-2 pb-2 pr-2">
          <button
            type="button"
            disabled={disabled}
            className="p-2 text-muted-foreground hover:text-foreground transition-colors rounded-lg hover:bg-muted disabled:opacity-50"
          >
            <Paperclip className="w-4 h-4" />
          </button>

          {isStreaming ? (
            <button
              type="button"
              onClick={onStop}
              className="p-2 bg-destructive text-destructive-foreground rounded-lg hover:bg-destructive/90 transition-colors"
              title="停止生成"
            >
              <Square className="w-4 h-4" />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSend}
              disabled={!value.trim() || disabled}
              className="p-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ArrowUp className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
      <div className="text-center mt-2">
        <p className="text-[10px] text-muted-foreground/40">
          {t("chat.disclaimer")}
        </p>
      </div>
    </div>
  );
}
