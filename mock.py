# =============================================================================
# MOCK DEVICE CLASS FOR TESTING
# =============================================================================
class MockDMMDevice:
    """Simulates ADCMT 7352A responses for GUI testing without hardware."""
    def __init__(self):
        self.current_func_a = "F1"
        self.current_func_b = "F12"
        self.value_a = 0.5
        self.value_b = 0.3
        self.timeout = 2000
    
    def query(self, cmd):
        """Simulate device query responses."""
        import random
        # Add realistic variation to readings
        noise_a = random.gauss(0, 0.02)
        noise_b = random.gauss(0, 0.01)
        self.value_a = np.clip(self.value_a + noise_a, -10, 10)
        self.value_b = np.clip(self.value_b + noise_b, -5, 5)
        
        if "DSP1,MD?" in cmd:
            exp_a = f"{self.value_a:.5e}".replace('e', 'E')
            return f"S{exp_a},"
        elif "DSP2,MD?" in cmd:
            exp_b = f"{self.value_b:.5e}".replace('e', 'E')
            return f"S{exp_b},"
        return "S+0.00000E+00,"
    
    def write(self, cmd):
        """Simulate device command execution."""
        if "DSP1" in cmd and "F" in cmd:
            self.current_func_a = cmd.split(",")[1]
        elif "DSP2" in cmd and "F" in cmd:
            self.current_func_b = cmd.split(",")[1]
    
    def close(self):
        """Simulate device close."""
        pass