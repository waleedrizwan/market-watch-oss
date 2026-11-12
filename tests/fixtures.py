"""Synthetic pages and responses shaped like the real sources (values are made up)."""

DRAMX_HTML = """
<html><body>
<table><tbody><tr>
  <td class="title_left"><a href="/Price/Dram_Spot"><font face="Arial">DRAM Spot Price</font></a></td>
  <td class="title_right"><span class="tab_time">Last Update: Nov.12 2026    14:40 (GMT+8) <a href="#"><span>&lt;Price Notice&gt;</span></a></span></td>
</tr></tbody></table>
<table><tbody id="tb_NationalDramSpotPrice">
  <tr><td class="tab_title">Item</td><td class="tab_title">Daily High</td><td class="tab_title">Daily Low</td>
      <td class="tab_title">Session High</td><td class="tab_title">Session Low</td><td class="tab_title">Session Average</td>
      <td class="tab_title">Session Change</td></tr>
  <tr><td class="tab_tr_gray2"><a href="/Price/Dram_Spot"><img src="c.gif"> DDR5 16Gb (2Gx8)  4800/5600 </a></td>
      <td>11.00</td><td>9.00</td><td>11.00</td><td>9.00</td><td>10.123</td><td>0.00 %</td></tr>
  <tr><td class="tab_tr_gray2"><a href="/Price/Dram_Spot"> DDR4 16Gb (2Gx8) 3200 </a></td>
      <td>1,100.00</td><td>1,000.00</td><td>1,100.00</td><td>1,000.00</td><td>1,050.500</td><td>-0.15 %</td></tr>
</tbody></table>
<table><tbody><tr>
  <td class="title_left"><a href="/Price/Wafer_Spot"><font face="Arial">Wafer Spot Price</font></a></td>
  <td class="title_right"><span class="tab_time">Last Update:Nov.2 2026 14:40 (GMT+8)</span></td>
</tr></tbody></table>
<table><tbody>
  <tr><td class="tab_title">Item</td><td class="tab_title">Weekly High</td><td class="tab_title">Weekly Low</td>
      <td class="tab_title">Session High</td><td class="tab_title">Session Low</td><td class="tab_title">Session Average</td></tr>
  <tr><td class="tab_tr_gray2"> 512Gb TLC </td><td>5.00</td><td>4.00</td><td>5.00</td><td>4.00</td><td>4.444</td></tr>
</tbody></table>
</body></html>
"""

FRED_CSV = "observation_date,X\n2026-06-01,1.0\n2026-07-01,.\n2026-08-01,2.5\n2026-09-01,3.0\n"


class FakeResponse:
    def __init__(self, text="", json_data=None, status=200):
        self.text = text
        self._json = json_data
        self.status_code = status

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
