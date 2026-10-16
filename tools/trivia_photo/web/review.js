document.querySelectorAll('[data-decision]').forEach(button => {
  button.addEventListener('click', async () => {
    const card = button.closest('.card');
    const feedback = card.querySelector('.feedback');
    const buttons = card.querySelectorAll('button');
    buttons.forEach(b => b.disabled = true);
    try {
      const response = await fetch('/api/decision', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Trivia-Photo-Token': context.token},
        body: JSON.stringify({trivia_id: Number(card.dataset.id), decision: button.dataset.decision,
          rights_confirmed: card.querySelector('.rights-check')?.checked === true})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '保存できませんでした');
      feedback.textContent = result.message;
      const status = card.querySelector('.status');
      status.textContent = button.dataset.decision === 'approve' ? '承認済み' : '却下';
      status.className = 'status ' + (button.dataset.decision === 'approve' ? 'approved' : 'rejected');
    } catch (error) {
      feedback.textContent = error.message;
    } finally {
      buttons.forEach(b => b.disabled = false);
    }
  });
});
