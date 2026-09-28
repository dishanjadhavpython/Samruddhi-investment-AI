import { ReactNode } from "react";
import { Button, Modal } from "./ui";

interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  message: ReactNode;
  confirmText?: string;
  cancelText?: string;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  isProcessing?: boolean;
}

export default function ConfirmModal({
  isOpen,
  title,
  message,
  confirmText = "Confirm",
  cancelText = "Cancel",
  destructive = false,
  onConfirm,
  onCancel,
  isProcessing = false,
}: ConfirmModalProps) {
  return (
    <Modal
      open={isOpen}
      onClose={onCancel}
      title={title}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={isProcessing}>
            {cancelText}
          </Button>
          <Button
            variant={destructive ? "danger" : "primary"}
            onClick={onConfirm}
            loading={isProcessing}
            data-autofocus
            className={destructive ? "!bg-bad !text-white hover:!opacity-90" : ""}
          >
            {confirmText}
          </Button>
        </>
      }
    >
      <div className="text-[14px] leading-6 text-ink-2">{message}</div>
    </Modal>
  );
}
