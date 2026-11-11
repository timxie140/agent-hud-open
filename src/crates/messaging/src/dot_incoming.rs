//! The authenticated Dot inbox: original replies and proactive Codex messages.
use super::*;
use agent_hud_platform::dot;

impl Messaging {
    pub(crate) fn publish_dot_sessions(&self, host: &Host<'_>) {
        if !self.dot.enabled() {
            return;
        }
        let sessions: Vec<Value> = if self.preferences.enabled {
            sessions(host.snapshot).filter(|row| row["source"] == "codex").take(100)
                .map(|row| json!({"id":row["id"],"client":"codex","title":row["title"],
                    "state":match state(row) { "running" => "running", "waitingForApproval" => "waiting", _ => "idle" }})).collect()
        } else {
            Vec::new()
        };
        let _ = self.dot.call(
            "sessions",
            json!({"enabled":self.preferences.enabled,
            "platform":std::env::consts::OS,"sessions":sessions}),
        );
    }

    pub(crate) fn maintain_dot(&mut self, host: &Host<'_>, now: i64) {
        if !self.preferences.enabled || !self.dot.enabled() {
            return;
        }
        self.confirm_received_dot();
        let Ok(value) = self.dot.call("pending", json!({})) else {
            return;
        };
        let Some(rows) = value["messages"].as_array() else {
            return;
        };
        for row in rows.iter().take(8) {
            self.deliver_dot(row, host, now);
        }
    }

    fn deliver_dot(&mut self, row: &Value, host: &Host<'_>, now: i64) {
        let Some(id) = row["id"].as_str() else {
            return;
        };
        let Ok(claim) = self
            .dot
            .call("claim", json!({"id":id,"receiptProtocol":"native-v2"}))
        else {
            return;
        };
        if claim["claimed"] != true {
            return;
        }
        if claim["receiptProtocol"] != "native-v2" {
            return; // Unknown sidecar: keep the durable reservation, never send.
        }
        let Some(binding) = self.dot_target(row, &claim, host) else {
            self.refuse_dot(id, "recipient_unavailable");
            return;
        };
        let next_pass = binding
            .parent
            .as_ref()
            .map_or(1, |p| p.count.saturating_add(1));
        if self
            .preferences
            .limit
            .is_some_and(|limit| next_pass > limit)
        {
            self.refuse_dot(id, "pass_limit");
            return;
        }
        let (Some(delivery_id), Some(text)) = (claim["replyId"].as_str(), claim["text"].as_str())
        else {
            return;
        };
        let header = if let Some(parent) = &binding.parent {
            format!(
                "[Agent HUD · Dot Luo; reply_to={}; reply_id={delivery_id}]",
                parent.id
            )
        } else {
            format!("[Agent HUD · Dot Luo; message_id={delivery_id}]")
        };
        let delivered = format!("{header}\n{text}");
        let receipt = self.clients.send(SendRequest {
            provider: Provider::Codex,
            session_id: binding.to.session_id.clone(),
            request_id: delivery_id.into(),
            text: delivered.clone(),
            form: PromptForm::Labelled,
            operation: Operation::SteerOrEnqueue,
            expected_turn_id: None,
        });
        let (state, native) = match &receipt {
            Ok(receipt) => {
                use agent_hud_core::naming::surfaces::{Category, Surface};
                self.clients
                    .delivered(receipt, &Surface::new(Category::Mcp, "dot"), now);
                let state = delivered_or_refused(receipt.state);
                let native = match state {
                    "refused" => "refused",
                    "uncertain" => "uncertain",
                    _ => "accepted",
                };
                (state, json!({"state":native,"deliveryMode":receipt.state}))
            }
            Err(_) => ("uncertain", json!({"state":"uncertain"})),
        };
        // The claim is durable even if completion or journal publication fails.
        let _ = self.dot.call("complete", json!({"id":id,"native":native}));
        let sender = Party {
            client: "dot".into(),
            session_id: dot::SESSION.into(),
            title: Some("Luo".into()),
        };
        let chain = binding
            .parent
            .as_ref()
            .map_or_else(|| delivery_id.into(), |p| p.chain.clone());
        let left = binding.parent.as_ref().map_or_else(
            || dot::SESSION.into(),
            |p| self.left_of(&p.chain, &binding.to.session_id),
        );
        self.journal.add(Message {
            id: delivery_id.into(),
            kind: Kind::Send,
            chain,
            count: next_pass,
            from: sender.clone(),
            to: binding.to.clone(),
            form: PromptForm::Labelled,
            reply_to: binding.parent.as_ref().map(|p| p.id.clone()),
            request_id: delivery_id.into(),
            sent_at_ms: now,
            cursor: None,
            fingerprint: transcript::fingerprint(&delivered),
            state: state.into(),
            reason: None,
            turn: None,
            answered: false,
            replied_by: None,
        });
        (self.fly)(flight(
            &sender,
            &binding.to,
            same_session(&left, dot::SESSION),
            false,
            matches!(state, "refused" | "uncertain"),
        ));
        if let Some(parent) = binding.parent {
            if let Some(parent) = self.journal.messages_mut().find(|p| p.id == parent.id) {
                parent.replied_by = Some(delivery_id.into());
                parent.answered = true;
            }
            self.journal.save();
        }
    }

    fn dot_target(&self, row: &Value, claim: &Value, host: &Host<'_>) -> Option<DotTarget> {
        if row["source"] != claim["source"] && !claim["source"].is_null() {
            return None;
        }
        if row["origin"] != claim["origin"] && !claim["origin"].is_null() {
            return None;
        }
        if row["origin"] == "dot" {
            if claim["origin"] != "dot" {
                return None;
            }
            let session = row["source"].as_str()?.strip_prefix("codex:")?;
            let target = find(host.snapshot, session)?;
            if target["source"] != "codex" || !target["parentId"].is_null() {
                return None;
            }
            return Some(DotTarget {
                to: party(host.snapshot, "codex", session),
                parent: None,
            });
        }
        let parent = self.journal.find(row["id"].as_str()?)?.clone();
        if parent.to.client != "dot"
            || parent.from.client != "codex"
            || row["source"] != format!("codex:{}", parent.from.session_id)
        {
            return None;
        }
        Some(DotTarget {
            to: parent.from.clone(),
            parent: Some(parent),
        })
    }

    fn refuse_dot(&self, id: &str, reason: &str) {
        let _ = self.dot.call(
            "complete",
            json!({"id":id,"native":{"state":"refused","reasonCode":reason}}),
        );
    }
}

struct DotTarget {
    to: Party,
    parent: Option<Message>,
}
